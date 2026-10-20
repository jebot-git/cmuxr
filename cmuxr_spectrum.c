/* SPDX-License-Identifier: GPL-2.0-or-later
 * Goertzel analysis of successfully submitted PCM. No I/O on the audio thread. */
#include "cmuxr_spectrum.h"
#include <math.h>
#include <pthread.h>
#include <stdint.h>
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static float published[16];
void cmuxr_spectrum_get(float bands[16])
{
 pthread_mutex_lock(&mutex);
 for (int b=0;b<16;b++) bands[b]=published[b];
 pthread_mutex_unlock(&mutex);
}
void cmuxr_spectrum_feed(const char *data, int size, sample_format_t sf)
{
 static double q1[16],q2[16],coeff[16];
 static sample_format_t previous; static int count;
 int bytes=sf_get_sample_size(sf), channels=sf_get_channels(sf), rate=sf_get_rate(sf);
 if (!channels || !rate || bytes<1 || bytes>4) return;
 if (previous!=sf) {
  previous=sf; count=0;
  for(int b=0;b<16;b++) { q1[b]=q2[b]=0; coeff[b]=2*cos(6.283185307179586*fmin(60*pow(1.42,b),rate*.45)/rate); }
 }
 for(int i=0;i+bytes*channels<=size;i+=bytes*channels) {
  double sample=0;
  for(int ch=0;ch<channels;ch++) {
   const unsigned char *p=(const unsigned char *)data+i+ch*bytes; uint32_t v=0;
   for(int j=0;j<bytes;j++) v=(v<<8)|p[sf_get_bigendian(sf)?j:bytes-1-j];
   double midpoint=ldexp(1.0,bytes*8-1);
   double value=sf_get_signed(sf)? ((v & (1u<<(bytes*8-1)))?(double)v-2*midpoint:v):(double)v-midpoint;
   sample+=value/midpoint/channels;
  }
  /* Hann window suppresses spectral leakage. */
  sample*=.5-.5*cos(6.283185307179586*count/1023);
  for(int b=0;b<16;b++) { double q=sample+coeff[b]*q1[b]-q2[b]; q2[b]=q1[b]; q1[b]=q; }
  if(++count==1024) {
   float bands[16];
   for(int b=0;b<16;b++) { double power=fmax(0,q1[b]*q1[b]+q2[b]*q2[b]-coeff[b]*q1[b]*q2[b]); bands[b]=fmin(1,log1p(sqrt(power))/5); q1[b]=q2[b]=0; }
   pthread_mutex_lock(&mutex);
   for(int b=0;b<16;b++) published[b]=bands[b];
   pthread_mutex_unlock(&mutex); count=0;
  }
 }
}
