/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef CMUXR_SPECTRUM_H
#define CMUXR_SPECTRUM_H
#include "sf.h"
void cmuxr_spectrum_feed(const char *data, int size, sample_format_t sf);
void cmuxr_spectrum_get(float bands[16]);
#endif
