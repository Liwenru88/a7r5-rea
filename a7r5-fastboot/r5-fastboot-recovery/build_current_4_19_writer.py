#!/usr/bin/env python3
"""Build a writer restricted to one audited sparse image and flash:nflasha2."""
from __future__ import annotations
import argparse, hashlib, subprocess
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[2]/'a7r5-firmware-features/firmware-runtime/dependencies/native12-combined/upstream/analysis/r5_verifykey_skip_flash_20261014/partition1_usb.c'
def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--sparse',type=Path,required=True);p.add_argument('--expected-sparse-sha256');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 sparse=a.sparse.resolve(); expected=a.expected_sparse_sha256 or digest(sparse)
 if digest(sparse)!=expected: raise SystemExit('sparse SHA-256 mismatch')
 text=SOURCE.read_text(); start=text.index('static int allowed('); end=text.index('static unsigned char staged',start)
 text=text[:start]+f'''static int allowed(const char *s) {{ return !strncmp(s,"download:/",10) || !strcmp(s,"flash:nflasha2"); }}\nstatic int download_approved=0, write_sent=0;\n'''+text[end:]
 text=text.replace('ce51008ae51696004488b02ae291b23390edcea70870d0c60280ebeccd1a53ee',expected)
 marker='static int command(const char *arg) {\n'; guard='    int is_flash=!strcmp(arg,"flash:nflasha2"); if(is_flash && (!download_approved || write_sent)) return -1; if(is_flash) write_sent=1;\n'; text=text.replace(marker,marker+guard,1)
 old='if(!memcmp(b,"OKAY",4)){if(saved_path)'; new='if(!memcmp(b,"OKAY",4)){if(!strncmp(arg,"download:/",10)){if(downloading)return -1;download_approved=1;}if(saved_path)'; text=text.replace(old,new,1)
 oldmain='int main(int argc,char **argv) {\n    setbuf(stdout,NULL);'; newmain='int main(int argc,char **argv) {\n    setbuf(stdout,NULL); if(argc!=3 || strncmp(argv[1],"download:/",10) || strcmp(argv[2],"flash:nflasha2")) return 2;'; text=text.replace(oldmain,newmain,1)
 a.output.mkdir(mode=0o700,parents=True,exist_ok=True); c=a.output/'current_4_19_writer.c'; b=a.output/'current_4_19_writer'; c.write_text(text); subprocess.run(['/usr/bin/clang','-O2','-Wall','-Wextra',str(c),'-o',str(b),'-framework','IOKit','-framework','CoreFoundation'],check=True); print(b); return 0
if __name__=='__main__': raise SystemExit(main())
