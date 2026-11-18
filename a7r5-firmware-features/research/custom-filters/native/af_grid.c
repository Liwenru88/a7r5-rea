/* 依据公开5×9×9平面格式独立实现；无文件、设备或动态分配。 */
#include "af_grid.h"
#include <float.h>
static int finite(float x) { return x==x && x<=FLT_MAX && x>=-FLT_MAX; }
static float clip(float v,float low,float high) { return v<low?low:(v>high?high:v); }
static int apart(const void *a,size_t n,const void *b,size_t m) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a && b && x<=UINTPTR_MAX-n && y<=UINTPTR_MAX-m && (x+n<=y || y+m<=x);
}
int af_grid_model_valid(const AfGridModel *m) {
    unsigned any=0;
    if (!m || m->schema!=1 || !m->base_mask || (m->base_mask&~0x603ffu) || m->smooth>1) return AF_INVALID;
    /* 原捕获仅覆盖固定PT非网格参数，本ABI不能校验那些条件。
     * 禁止把其原始数据摘要当作ST/PT通用模型身份；另名数学夹具不授予机身资格。 */
    static const uint8_t paired_v2[32]={0x88,0x79,0x49,0x9f,0xbd,0x9b,0x24,0x89,
        0x9d,0xcb,0xd8,0xfe,0xe4,0x13,0x5b,0x80,0x6f,0xdc,0xba,0x1f,0xd1,0x8a,0x67,0x7b,
        0x09,0x0b,0x7a,0xf2,0x12,0xb8,0x5a,0x45};
    unsigned difference=0;
    for (unsigned i=0;i<32;++i) difference|=m->sha256[i]^paired_v2[i];
    if (!difference) return AF_INVALID;
    for (unsigned i=0;i<12;++i) if (!finite(m->coordinates[i]) || m->coordinates[i]<-16 || m->coordinates[i]>16) return AF_INVALID;
    for (unsigned i=0;i<36;++i) if (!finite(m->response[i]) || m->response[i]<-16 || m->response[i]>16) return AF_INVALID;
    for (unsigned i=0;i<32;++i) any|=m->sha256[i];
    return any?AF_OK:AF_INVALID;
}
int af_grid_row(const AfGridModel *m,const float rgb[3],AfGridRow *out) {
    AfGridRow r={0};unsigned low[3];float f[3];
    if (af_grid_model_valid(m)!=AF_OK || !rgb || !out || !apart(out,sizeof(*out),m,sizeof(*m))) return AF_INVALID;
    for (unsigned c=0;c<3;++c) if (!finite(rgb[c]) || rgb[c]<0 || rgb[c]>1) return AF_INVALID;
    for (unsigned c=0;c<3;++c) {
        float v=m->coordinates[c*4+3];
        r.base[c]=rgb[c];
        for (unsigned j=0;j<3;++j) v+=rgb[j]*m->coordinates[c*4+j];
        v=clip(v*(c?8:4)+(c?4:0),0,c?8:4);
        low[c]=(unsigned)v;
        if (low[c]>=(c?8u:4u)) --low[c];
        f[c]=v-(float)low[c];
    }
    for (unsigned i=0;i<8;++i) {
        unsigned y=(i>>2)&1,u=(i>>1)&1,v=i&1;
        r.index[i]=(uint16_t)((low[0]+y)*81+(low[1]+u)*9+low[2]+v);
        r.weights[i]=(y?f[0]:1-f[0])*(u?f[1]:1-f[1])*(v?f[2]:1-f[2]);
    }
    for (unsigned c=0;c<3;++c) for (unsigned o=0;o<3;++o) {
        float v=m->response[c*3+o];
        if (m->smooth) for (unsigned j=0;j<3;++j) v+=(rgb[j]-.5f)*m->response[(3+3*c+j)*3+o];
        r.response[c*3+o]=v/256;
    }
    *out=r;return AF_OK;
}
int af_grid_predict(const AfGridModel *m,const int8_t *grid,const float rgb[3],float out[3]) {
    AfGridRow row;float predicted[3];
    if (!grid || !out || af_grid_row(m,rgb,&row)!=AF_OK ||
        !apart(out,12,grid,AF_GRID_BYTES) || !apart(out,12,m,sizeof(*m))) return AF_INVALID;
    for (unsigned i=0;i<AF_GRID_BYTES;++i) if (grid[i]<-64 || grid[i]>63) return AF_INVALID;
    for (unsigned o=0;o<3;++o) {
        float v=rgb[o];
        for (unsigned c=0;c<3;++c) {
            float correction=0;
            for (unsigned j=0;j<8;++j) correction+=row.weights[j]*grid[c*AF_GRID_NODES+row.index[j]];
            v+=correction*row.response[c*3+o];
        }
        predicted[o]=clip(v,0,1);
    }
    for (unsigned o=0;o<3;++o) out[o]=predicted[o];
    return AF_OK;
}
int af_grid_pack(const int8_t *grid,const uint16_t *permutation,unsigned level,uint32_t *out) {
    uint8_t seen[AF_GRID_NODES]={0};
    if (!grid || !permutation || !out || !level || level>8 ||
        !apart(out,AF_GRID_NODES*4,grid,AF_GRID_BYTES) ||
        !apart(out,AF_GRID_NODES*4,permutation,AF_GRID_NODES*2)) return AF_INVALID;
    for (unsigned i=0;i<AF_GRID_NODES;++i) {
        unsigned n=permutation[i];
        if (n>=AF_GRID_NODES || seen[n]) return AF_INVALID;
        seen[n]=1;
    }
    for (unsigned i=0;i<AF_GRID_BYTES;++i) if (grid[i]<-64 || grid[i]>63) return AF_INVALID;
    for (unsigned i=0;i<AF_GRID_NODES;++i) {
        uint32_t word=0;
        for (unsigned c=0;c<3;++c) {
            int v=(int)grid[c*AF_GRID_NODES+i]*(int)level;
            /* 精确模拟ARM算术右移，避免负整数除法向零舍入。 */
            v=v>=0?v/8:-((-v+7)/8);
            word|=((uint32_t)v&127u)<<(22-10*c);
        }
        out[permutation[i]]=word;
    }
    return AF_OK;
}
