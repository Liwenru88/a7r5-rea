#ifndef GPE_COPY_H
#define GPE_COPY_H
struct gpe_copy_plan {
    unsigned long long destination, source;
    unsigned long destination_span, source_span, destination_offset, source_offset;
    unsigned long destination_pitch, source_pitch, line;
    unsigned int rows;
};
int gpe_plan_copy(const unsigned int *, struct gpe_copy_plan *);
int gpe_copy_rows(unsigned char *, unsigned long, const unsigned char *, unsigned long,
                  const struct gpe_copy_plan *);
#endif
