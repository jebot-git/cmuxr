// SPDX-License-Identifier: MIT
#pragma once
#include <FL/Fl_Menu_Bar.H>
#include <FL/Fl_Window.H>
#include <memory>
#include <string>
// Export real FLTK commands over DBusMenu and associate the owning window via
// KDE's native Wayland appmenu protocol (X11 window properties otherwise).
class DesktopMenu {
  struct Impl;
  std::unique_ptr<Impl> impl;

public:
  DesktopMenu(Fl_Window &, Fl_Menu_Bar &);
  ~DesktopMenu();
  std::string objectPath() const;
  std::string serviceName() const;
  DesktopMenu(const DesktopMenu &) = delete;
  DesktopMenu &operator=(const DesktopMenu &) = delete;
};
