// SPDX-License-Identifier: GPL-2.0-or-later
#include "appearance.h"
#include "gpu-window.h"
#include <FL/Fl_Box.H>
#include <FL/Fl_Button.H>
#include <FL/Fl_Choice.H>
#include <FL/Fl_Double_Window.H>
#include <FL/Fl_Hold_Browser.H>
#include <FL/Fl_Native_File_Chooser.H>
#include <FL/fl_ask.H>
#include <cstring>
#include <sstream>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/un.h>
static std::string request(const std::string &command) {
  if (command.find_first_of("\r\n") != std::string::npos)
    throw std::runtime_error("Invalid command");
  const char *path = getenv("CMUS_SOCKET");
  if (!path)
    throw std::runtime_error("CMUS_SOCKET is not set; launch through cmuxr");
  int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
  if (fd < 0)
    throw std::runtime_error("Cannot create player socket");
  struct Guard {
    int fd;
    ~Guard() { close(fd); }
  } guard{fd};
  timeval timeout{0, 700000};
  setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
  setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
  sockaddr_un address{};
  address.sun_family = AF_UNIX;
  if (strlen(path) >= sizeof(address.sun_path))
    throw std::runtime_error("Player socket path is too long");
  strcpy(address.sun_path, path);
  if (connect(fd, (sockaddr *)&address, sizeof(address)))
    throw std::runtime_error("Player unavailable");
  auto line = command + "\n";
  size_t sent = 0;
  while (sent < line.size()) {
    auto n = send(fd, line.data() + sent, line.size() - sent, MSG_NOSIGNAL);
    if (n <= 0)
      throw std::runtime_error("Player command failed");
    sent += n;
  }
  std::string result;
  char buf[8192];
  while (result != "\n" &&
         (result.size() < 2 || result.substr(result.size() - 2) != "\n\n")) {
    auto n = recv(fd, buf, sizeof(buf), 0);
    if (n <= 0)
      throw std::runtime_error("Player response interrupted");
    result.append(buf, n);
    if (result.size() > 4 * 1024 * 1024)
      throw std::runtime_error("Player response too large");
  }
  return result;
}
static std::string unescape(std::string s) {
  std::string out;
  for (size_t i = 0; i < s.size(); ++i) {
    if (s[i] == '\\' && i + 1 < s.size()) {
      ++i;
      out += s[i] == 'n' ? '\n' : s[i];
    } else
      out += s[i];
  }
  return out;
}
#include "desktop-menu.h"
#include "status-icon.h"
#include <FL/Fl_Check_Button.H>
#include <FL/Fl_Input.H>
#include <FL/Fl_Menu_Bar.H>
#include <FL/Fl_Value_Slider.H>
#include <array>
#include <deque>
#include <future>
class Spectrum : public Fl_Widget {
  std::array<double, 16> levels{}, target{};

public:
  Spectrum(int x, int y, int w, int h) : Fl_Widget(x, y, w, h) {}
  void set(const std::string &values) {
    std::istringstream input(values);
    for (auto &value : target) {
      double next = 0;
      input >> next;
      value = std::clamp(next, 0., 1.);
    }
  }
  void animate() {
    bool changed = false;
    for (int i = 0; i < 16; ++i) {
      double value = std::max(target[i], levels[i] * .86);
      if (std::abs(value - levels[i]) > .001)
        changed = true;
      levels[i] = value;
    }
    if (changed)
      redraw();
  }
  void draw() override {
    fl_push_clip(x(), y(), w(), h());
    fl_color(FL_BACKGROUND2_COLOR);
    fl_rectf(x(), y(), w(), h());
    for (int i = 0; i < 16; ++i) {
      int width = std::max(1, w() / 16 - 4),
          height = std::round(levels[i] * (h() - 6));
      fl_color(FL_SELECTION_COLOR);
      fl_rectf(x() + i * w() / 16 + 2, y() + h() - height - 3, width, height);
    }
    fl_pop_clip();
  }
};
class Player : public dx::GpuWindow {
  Fl_Menu_Bar menu{0, 0, 900, 25};
  Fl_Box now{10, 28, 880, 32};
  Fl_Button previous{10, 65, 120, 30, "Previous"},
      play{140, 65, 150, 30, "Play / Pause"}, stop{300, 65, 100, 30, "Stop"},
      next{410, 65, 100, 30, "Next"}, add{520, 65, 110, 30, "Add files"};
  Fl_Choice source{650, 65, 240, 30};
  Fl_Hold_Browser tracks{10, 110, 880, 370};
  Fl_Button pageBack{10, 490, 120, 30, "Page back"},
      pageNext{145, 490, 120, 30, "Page next"};
  Fl_Box info{280, 490, 610, 30};
  Spectrum spectrum{10, 535, 880, 60};
  Fl_Input filter{90, 610, 340, 30, "Filter page"};
  Fl_Check_Button floor{480, 610, 350, 30, "XR spectrum floor"};
  Fl_Value_Slider seek{10, 650, 680, 25}, volume{735, 650, 155, 25};
  std::unique_ptr<DesktopMenu> desktop;
  std::unique_ptr<StatusIcon> tray;
  bool trayRequested = false, trayHandled = false;
  std::vector<std::string> files, visibleFiles;
  int offset = 0, total = 0;
  std::future<std::string> pageTask, statusTask, commandTask;
  std::deque<std::string> commands;
  bool pagePending = false;
  uint64_t pageGeneration = 0, pageStarted = 0;
  std::chrono::steady_clock::time_point statusTime{};
  Json preferences;
  double duration = 0;
  static void tick(void *p) {
    auto s = (Player *)p;
    s->poll();
    Fl::repeat_timeout(.05, tick, p);
  }
  static std::future<std::string> task(std::string value) {
    return std::async(std::launch::async, [value] { return request(value); });
  }
  void error(const std::exception &e) { info.copy_label(e.what()); }
  void command(std::string value) {
    if (commands.size() < 128)
      commands.push_back(std::move(value));
  }
  void showFiles() {
    tracks.clear();
    visibleFiles.clear();
    std::string search = filter.value();
    std::transform(search.begin(), search.end(), search.begin(), ::tolower);
    for (auto &file : files) {
      auto name = std::filesystem::path(file).filename().string(), match = name;
      std::transform(match.begin(), match.end(), match.begin(), ::tolower);
      if (!search.empty() && match.find(search) == std::string::npos)
        continue;
      visibleFiles.push_back(file);
      tracks.add(name.c_str());
    }
  }
  std::string selected() {
    int i = tracks.value() - 1;
    return i >= 0 && i < int(visibleFiles.size()) ? visibleFiles[i]
                                                  : std::string();
  }
  std::filesystem::path settingsPath() {
    auto root = getenv("XDG_CONFIG_HOME");
    return std::filesystem::path(
               root ? root
                    : std::string(getenv("HOME") ? getenv("HOME") : "/tmp") +
                          "/.config") /
           "cmuxr/settings.json";
  }
  void store() {
    try {
      auto path = settingsPath();
      std::filesystem::create_directories(path.parent_path());
      preferences["floor_enabled"] = bool(floor.value());
      auto temp = path;
      temp += ".tmp";
      std::ofstream(temp) << preferences.dump(2);
      std::filesystem::rename(temp, path);
    } catch (...) {
    }
  }
  void addFiles(bool directory = false) {
    Fl_Native_File_Chooser chooser;
    chooser.type(directory ? Fl_Native_File_Chooser::BROWSE_DIRECTORY
                           : Fl_Native_File_Chooser::BROWSE_MULTI_FILE);
    if (chooser.show() == 0) {
      for (int i = 0; i < chooser.count(); ++i)
        command("add -l " +
                std::filesystem::absolute(chooser.filename(i)).string());
    }
  }
  void menuCommand(std::string name) {
    if ((name == "Play / Pause" || name == "Play or pause"))
      command("player-pause");
    else if (name == "Stop")
      command("player-stop");
    else if (name == "Previous")
      command("player-prev");
    else if (name == "Next")
      command("player-next");
    else if (name == "Add files")
      addFiles();
    else if (name == "Add folder")
      addFiles(true);
    else if (name == "Update library")
      command("update-cache");
    else if (name == "Refresh")
      reload();
    else if (name == "Play selected") {
      auto file = selected();
      if (!file.empty())
        command("player-play " + file);
    } else if (name == "Queue selected") {
      auto file = selected();
      if (!file.empty())
        command("add -q " + file);
    } else if (name == "Remove from library") {
      auto file = selected();
      if (!file.empty() &&
          fl_choice("Remove selected track from the library? The file is kept.",
                    "Cancel", "Remove", nullptr) == 1) {
        std::string escaped;
        for (auto c : file) {
          if (c == '\\')
            escaped += "\\\\";
          else if (c == '\n')
            escaped += "\\n";
          else
            escaped += c;
        }
        command("cmuxr-remove " + escaped);
      }
    } else if (name == "Shuffle")
      command("toggle shuffle");
    else if (name == "Repeat")
      command("toggle repeat");
    else if (name == "Seek backward")
      command("seek -5");
    else if (name == "Seek forward")
      command("seek +5");
    else if (name == "Volume up")
      command("vol +5%");
    else if (name == "Volume down")
      command("vol -5%");
    else if (name == "Toggle XR floor") {
      floor.value(!floor.value());
      store();
    } else if (name == "Quit") {
      closed = true;
      hide();
    }
  }

public:
  bool closed = false;
  Player(bool trayOnly = false) : dx::GpuWindow(900, 700, "cmuxr — Music") {
    xclass("org.domed.cmuxr");
    source.add("Playlist|Library|Queue");
    source.value(0);
    tracks.format_char(0);
    tracks.callback(
        [](Fl_Widget *, void *p) {
          auto s = (Player *)p;
          if (Fl::event_clicks()) {
            auto file = s->selected();
            if (!file.empty())
              s->command("player-play " + file);
          }
        },
        this);
    previous.callback(
        [](Fl_Widget *, void *p) { ((Player *)p)->command("player-prev"); },
        this);
    play.callback(
        [](Fl_Widget *, void *p) { ((Player *)p)->command("player-pause"); },
        this);
    stop.callback(
        [](Fl_Widget *, void *p) { ((Player *)p)->command("player-stop"); },
        this);
    next.callback(
        [](Fl_Widget *, void *p) { ((Player *)p)->command("player-next"); },
        this);
    add.callback([](Fl_Widget *, void *p) { ((Player *)p)->addFiles(); }, this);
    source.callback(
        [](Fl_Widget *, void *p) {
          auto s = (Player *)p;
          s->offset = 0;
          s->reload();
        },
        this);
    pageBack.callback(
        [](Fl_Widget *, void *p) {
          auto s = (Player *)p;
          s->offset = std::max(0, s->offset - 128);
          s->reload();
        },
        this);
    pageNext.callback(
        [](Fl_Widget *, void *p) {
          auto s = (Player *)p;
          if (s->offset + 128 < s->total) {
            s->offset += 128;
            s->reload();
          }
        },
        this);
    filter.when(FL_WHEN_CHANGED);
    filter.callback([](Fl_Widget *, void *p) { ((Player *)p)->showFiles(); },
                    this);
    floor.callback([](Fl_Widget *, void *p) { ((Player *)p)->store(); }, this);
    for (auto item : std::vector<std::pair<const char *, int>>{
             {"File/Add files", FL_CTRL + 'o'},
             {"File/Add folder", 0},
             {"File/Quit", FL_CTRL + 'q'},
             {"Playback/Play or pause", ' '},
             {"Playback/Stop", 0},
             {"Playback/Previous", FL_CTRL + FL_Left},
             {"Playback/Next", FL_CTRL + FL_Right},
             {"Playback/Seek backward", FL_ALT + FL_Left},
             {"Playback/Seek forward", FL_ALT + FL_Right},
             {"Playback/Volume up", '+'},
             {"Playback/Volume down", '-'},
             {"Playback/Shuffle", 0},
             {"Playback/Repeat", 0},
             {"Library/Play selected", FL_Enter},
             {"Library/Queue selected", FL_CTRL + 'e'},
             {"Library/Remove from library", FL_Delete},
             {"Library/Update library", 0},
             {"Library/Refresh", FL_F + 5},
             {"View/Toggle XR floor", 0}})
      menu.add(
          item.first, item.second,
          [](Fl_Widget *w, void *p) {
            ((Player *)p)->menuCommand(((Fl_Menu_ *)w)->mvalue()->label());
          },
          this);
    seek.type(FL_HOR_NICE_SLIDER);
    seek.range(0, 1);
    seek.callback(
        [](Fl_Widget *, void *p) {
          auto s = (Player *)p;
          s->command("seek " + std::to_string(int(s->seek.value())));
        },
        this);
    volume.type(FL_HOR_NICE_SLIDER);
    volume.range(0, 100);
    volume.value(100);
    volume.callback(
        [](Fl_Widget *, void *p) {
          auto s = (Player *)p;
          s->command("vol " + std::to_string(int(s->volume.value())) + "%");
        },
        this);
    now.align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE);
    info.align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE);
    end();
    resizable(tracks);
    size_range(500, 430);
    try {
      std::ifstream file(settingsPath());
      file >> preferences;
    } catch (...) {
      preferences = Json::object();
    }
    floor.value(preferences.value("floor_enabled", true));
    desktop = std::make_unique<DesktopMenu>(*this, menu);
    tray = std::make_unique<StatusIcon>(*desktop);
    trayRequested = trayOnly;
    tray->activate = [this] {
      show();
      take_focus();
    };
    tray->scroll = [this](int delta) {
      command(delta > 0 ? "vol +5%" : "vol -5%");
    };
    callback(
        [](Fl_Widget *, void *p) {
          auto s = (Player *)p;
          if (s->tray && s->tray->available())
            s->hide();
          else {
            s->closed = true;
            s->hide();
          }
        },
        this);
    Fl::add_timeout(.05, tick, this);
    reload();
  }
  ~Player() { Fl::remove_timeout(tick, this); }
  void reload() {
    ++pageGeneration;
    pagePending = true;
    files.clear();
    showFiles();
  }
  void poll() {
    for (auto path : {"Library/Play selected", "Library/Queue selected",
                      "Library/Remove from library"})
      dx::enable_menu(menu, path, !selected().empty());

    if (!shown() && tray && !tray->available() && !closed)
      show();
    if (trayRequested && !trayHandled && tray && tray->available()) {
      trayHandled = true;
      hide();
    }
    if (commandTask.valid() && commandTask.wait_for(std::chrono::seconds(0)) ==
                                   std::future_status::ready) {
      try {
        auto result = commandTask.get();
        if (result.rfind("error", 0) == 0)
          info.copy_label(result.c_str());
        reload();
      } catch (const std::exception &e) {
        error(e);
      }
    }
    if (!commandTask.valid() && !commands.empty()) {
      auto value = commands.front();
      commands.pop_front();
      commandTask = task(value);
    }
    if (pageTask.valid() && pageTask.wait_for(std::chrono::seconds(0)) ==
                                std::future_status::ready) {
      try {
        auto response = pageTask.get();
        if (pageStarted == pageGeneration) {
          std::istringstream lines(response);
          std::string line;
          files.clear();
          while (std::getline(lines, line)) {
            if (line.rfind("total ", 0) == 0)
              total = std::stoi(line.substr(6));
            else if (line.rfind("track ", 0) == 0) {
              auto pos = line.find(' ', 6);
              if (pos != std::string::npos)
                files.push_back(unescape(line.substr(pos + 1)));
            }
          }
          showFiles();
          info.copy_label((std::to_string(total ? offset + 1 : 0) + "–" +
                           std::to_string(offset + files.size()) + " of " +
                           std::to_string(total))
                              .c_str());
        }
      } catch (const std::exception &e) {
        error(e);
      }
    }
    if (!pageTask.valid() && pagePending) {
      pagePending = false;
      pageStarted = pageGeneration;
      pageTask = task(std::string("cmuxr-list ") +
                      (source.value() == 0   ? "playlist"
                       : source.value() == 1 ? "library"
                                             : "queue") +
                      " " + std::to_string(offset) + " 128");
    }
    if (statusTask.valid() && statusTask.wait_for(std::chrono::seconds(0)) ==
                                  std::future_status::ready) {
      try {
        auto response = statusTask.get();
        std::istringstream lines(response);
        std::string line, text;
        double position = 0;
        while (std::getline(lines, line)) {
          if (line.rfind("status ", 0) == 0 ||
              line.rfind("tag artist ", 0) == 0 ||
              line.rfind("tag title ", 0) == 0)
            text += unescape(line) + "  ";
          if (line.rfind("spectrum ", 0) == 0)
            spectrum.set(line.substr(9));
          if (line.rfind("duration ", 0) == 0)
            duration = std::stod(line.substr(9));
          if (line.rfind("position ", 0) == 0)
            position = std::stod(line.substr(9));
        }
        if (text != std::string(now.label() ? now.label() : ""))
          now.copy_label(text.c_str());
        if (tray)
          tray->setTitle(text);
        if (duration > 0) {
          seek.range(0, duration);
          if (Fl::pushed() != &seek)
            seek.value(position);
        }
      } catch (const std::exception &e) {
        error(e);
      }
    }
    if (!statusTask.valid() && std::chrono::steady_clock::now() - statusTime >
                                   std::chrono::milliseconds(100)) {
      statusTime = std::chrono::steady_clock::now();
      statusTask = task("status");
    }
    spectrum.animate();
  }
};
int main(int argc, char **argv) {
  dx::init();
  Fl::lock();
  bool tray = false;
  for (int i = 1; i < argc; ++i)
    if (std::string(argv[i]) == "--tray")
      tray = true;
  Player player(tray);
  if (auto fd = getenv("CMUXR_CONTROL_FD")) {
    Fl::add_fd(
        std::stoi(fd), FL_READ,
        [](int fd, void *p) {
          int c = accept(fd, nullptr, nullptr);
          if (c >= 0) {
            close(c);
            auto w = (Player *)p;
            w->show();
            w->take_focus();
          }
        },
        &player);
  }
  dx::smoke(player, argc, argv);
  while (!player.closed)
    Fl::wait(.05);
  return 0;
}
