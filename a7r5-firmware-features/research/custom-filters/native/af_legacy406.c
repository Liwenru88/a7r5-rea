#include "af_legacy406.h"
#include "af_sha256.h"
static const char ap_sha[]="d15933ceb5ff9ad0b4f789cbabd6ff0a51526472dd35c90db97196dd227820e9";
static const char cp_sha[]="18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97";
static const char *const names[6]={"Classic Neg.","Classic Chrome","Nostalgic Neg.","Astia","GR Positive Film","GR Negative Film"};
static const char *const grids[6]={
 "0b28eb22a523119e35cb4946469ce787b248a5f9ddee0e4a59a3ebf69ba8196f",
 "1105e2b2e706dcf1e47fda9a379089c99fa3d91d135e3a20dcb23a6ca94a6696",
 "205db27f0cca8da9233a2332167faa47ed651d8593a808529b1cb836dbe7dc79",
 "446e2595e1692e26e492d710eb747b4b57764aeb6ed45862e97a0a8b8b806139",
 "064fc9aaf4bdd64c7acc2cc1bd922b4264a73e8d41c05710ee62455b8f17c5c3",
 "6b7ee26631a7f1bdb0c73b23305c9afd6ab639ad8877c3cbf6224bbf75590372"};
static const char *const joints[6]={
 "fee5347b766ee4fd6f9b14fc3faf97680102e79c98d69172924ef033eaee7b35",
 "ce46f50e0b97a2236799f1b91da8aab3b53a4c28d11860ae723422c346bac923",
 "51f29fbf4c7c40e543c7706c2b3e0bad45626d954cc17a24bda5c1d0477721a0",
 "bb29c6d07126be82b7d2ed91d0baa3c118052abe098b18653223ee4254c73e7c",
 "dac3aa1626624068c4356724fd2f996041cc05f7dbfc2bb690acce7cd11df100",
 "9dc533aa06742f7099302bb773a2f65e503b0b9a8ce52b5c6b755a804f301343"};
static int apart(const void *a,size_t n,const void *b,size_t m){uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
 return a&&b&&x<=UINTPTR_MAX-n&&y<=UINTPTR_MAX-m&&(x+n<=y||y+m<=x);}
static unsigned nibble(char c){return (unsigned)(c<='9'?c-'0':c-'a'+10);}
static int digest(const uint8_t *bytes,const char *expected){
 for(unsigned i=0;i<32;++i)if(bytes[i]!=(nibble(expected[i*2])<<4|nibble(expected[i*2+1])))return 0;return 1;}
static int identity(const uint8_t *ap,const uint8_t *cp){return digest(ap,ap_sha)&&digest(cp,cp_sha);}
static void put16(uint8_t *p,int16_t v){p[0]=(uint8_t)v;p[1]=(uint8_t)((uint16_t)v>>8);}
int af_legacy406_asset_valid(const AfLegacy406Asset *a){
 if(!a||!a->slot||a->slot>6||!a->name_bytes||a->name_bytes>63)return AF_INVALID;
 unsigned index=a->slot-1,n=0;while(names[index][n])++n;
 if(n!=a->name_bytes||a->name[n])return AF_INVALID;
 for(unsigned i=0;i<n;++i)if(a->name[i]!=names[index][i])return AF_INVALID;
 uint8_t hash[32],joint[108];
 if(af_sha256(a->grid,sizeof(a->grid),hash)||!digest(hash,grids[index]))return AF_INVALID;
 for(unsigned i=0;i<3;++i)put16(joint+2*i,a->tone[i]);
 for(unsigned i=0;i<27;++i)put16(joint+6+2*i,a->matrix[i]);
 for(unsigned i=0;i<24;++i)put16(joint+60+2*i,a->cc1[i]);
 if(af_sha256(joint,sizeof(joint),hash)||!digest(hash,joints[index]))return AF_INVALID;
 return AF_OK;
}
static int values(const int32_t *live,const int32_t *shadow,uint32_t mask){
 if(mask&~0x7ffu)return AF_INVALID;
 for(unsigned i=0;i<3;++i)if(live[i]<0||live[i]>11)return AF_INVALID;
 AfPreset check={0};
 for(unsigned i=0;i<8;++i){if(live[i+3]<-128||live[i+3]>127)return AF_INVALID;check.params[i]=(int8_t)live[i+3];}
 if(af_validate(&check)!=AF_OK)return AF_INVALID;
 for(unsigned i=0;i<11;++i)if((mask&(1u<<i))&&shadow[i]!=live[i])return AF_BUSY;
 return AF_OK;
}
int af_legacy406_capture(const AfLegacy406Frame *before,const AfLegacy406Frame *after,
                         const AfLegacy406Asset *assets,AfLegacy406Snapshot *out){
 if(!before||!after||!assets||!out||!apart(before,sizeof(*before),after,sizeof(*after))||
    !apart(out,sizeof(*out),before,sizeof(*before))||!apart(out,sizeof(*out),after,sizeof(*after))||
    !apart(out,sizeof(*out),assets,6*sizeof(*assets))||!identity(before->ap_sha256,before->cp_sha256)||
    !identity(after->ap_sha256,after->cp_sha256))return AF_INVALID;
 if(before->model_ready!=1||after->model_ready!=1||before->photo_domain!=1||after->photo_domain!=1)return AF_BUSY;
 for(unsigned slot=0;slot<6;++slot){
  unsigned index=slot+10;int32_t live[11],shadow[11];uint32_t mask=before->shadow_mask[index];
  if(assets[slot].slot!=slot+1||af_legacy406_asset_valid(assets+slot)!=AF_OK)return AF_INVALID;
  if(mask!=after->shadow_mask[index])return AF_STALE;
  for(unsigned field=0;field<11;++field){
   live[field]=before->live[field][index];shadow[field]=before->shadow[field][index];
   if(live[field]!=after->live[field][index]||((mask&(1u<<field))&&shadow[field]!=after->shadow[field][index]))return AF_STALE;
  }
  int status=values(live,shadow,mask);if(status)return status;
 }
 /* 所有可失败校验结束后才发布；没有I/O、回调或目录安装。 */
 for(unsigned i=0;i<32;++i){out->ap_sha256[i]=before->ap_sha256[i];out->cp_sha256[i]=before->cp_sha256[i];}
 out->photo_domain=1;
 for(unsigned slot=0;slot<6;++slot){AfLegacy406Slot *s=out->slots+slot;unsigned index=slot+10;
  s->slot=slot+1;s->selector=slot+10;s->wire=slot+249;s->shadow_mask=before->shadow_mask[index];
  for(unsigned field=0;field<11;++field){s->live[field]=before->live[field][index];s->shadow[field]=before->shadow[field][index];}
  s->asset=assets[slot];
 }return AF_OK;
}
int af_legacy406_basis(const AfLegacy406Asset *asset,AfLegacy406Basis *out){
 if(!apart(asset,sizeof(*asset),out,sizeof(*out))||af_legacy406_asset_valid(asset)!=AF_OK)return AF_INVALID;
 AfLegacy406Basis next;int16_t expanded[27];
 for(unsigned plane=0;plane<3;++plane){const int16_t *m=asset->matrix+plane*9;int16_t *v=next.matrix+plane*6;
  const int values_[6]={-(int)m[1],-(int)m[2],-(int)m[3],-(int)m[5],-(int)m[6],-(int)m[7]};
  for(unsigned i=0;i<6;++i){if(values_[i]<-1024||values_[i]>1024)return AF_INVALID;v[i]=(int16_t)values_[i];}
 }
 if(af_joint_expand_matrix(next.matrix,expanded)!=AF_OK)return AF_INVALID;
 for(unsigned i=0;i<27;++i)if(expanded[i]!=asset->matrix[i])return AF_INVALID;
 for(unsigned i=0;i<3;++i)next.tone[i]=asset->tone[i];
 for(unsigned i=0;i<24;++i)next.cc1[i]=asset->cc1[i];
 for(unsigned i=0;i<AF_GRID_BYTES;++i)next.grid[i]=asset->grid[i];
 *out=next;return AF_OK;
}
int af_legacy406_gamma(const AfLegacy406Asset *asset,const uint32_t *stock,uint32_t *output){
 if(af_legacy406_asset_valid(asset)!=AF_OK||!apart(asset,sizeof(*asset),output,516))return AF_INVALID;
 return af_joint_gamma(stock,asset->tone,output);
}
int af_legacy406_to_ajr1(const AfLegacy406Snapshot *s,uint32_t slot,AfJointAsset *out){
 if(!s||!slot||slot>6||!apart(s,sizeof(*s),out,sizeof(*out))||!identity(s->ap_sha256,s->cp_sha256)||s->photo_domain!=1)return AF_INVALID;
 const AfLegacy406Slot *row=s->slots+slot-1;
 if(row->slot!=slot||row->selector!=slot+9||row->wire!=slot+248||row->asset.slot!=slot||
    af_legacy406_asset_valid(&row->asset)!=AF_OK||values(row->live,row->shadow,row->shadow_mask)!=AF_OK)return AF_INVALID;
 return AF_LEGACY406_UNSUPPORTED;
}
