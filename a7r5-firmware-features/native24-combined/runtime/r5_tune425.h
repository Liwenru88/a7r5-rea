#ifndef R5_TUNE425_H
#define R5_TUNE425_H
#include "sd_native_look.h"
struct r5_lut_directory;
#define R5_TUNE_PARAMETERS 8u
int r5_tune_library(struct r5_lut_directory *,const struct r5_look_set *);
int r5_tune_seed(unsigned,const int32_t [8]);
int r5_tune_value(unsigned,unsigned,int *);
int r5_tune_default(unsigned,unsigned,int *);
int r5_tune_edit(unsigned,unsigned,int);
int r5_tune_reset(unsigned);
unsigned r5_tune_changed(unsigned);
unsigned r5_tune_pending_changed(unsigned);
unsigned r5_tune_status(void);
int r5_tune_prepare(unsigned,int);
void r5_tune_commit(void);
int r5_tune_begin(struct r5_lut_directory *);
int r5_tune_save(struct r5_lut_directory *);
void r5_tune_finish(struct r5_lut_directory *);
int r5_tune_overlay(uint8_t *,size_t);
unsigned r5_tune_generation425(void);
unsigned r5_tune_observe425(const uint8_t *,size_t,unsigned *);
void r5_tune_sent425(unsigned,unsigned,int);
int r5_tune_verify(void);
void r5_tune_identity(const struct r5_native_look *,uint8_t [32]);
#endif
