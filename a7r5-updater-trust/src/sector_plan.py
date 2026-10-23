"""固定逻辑扇区计划与只读恢复分类；没有块设备打开或写入功能。"""
from filesystems import FatImage, require, sha
SIZE=25100288
SECTOR=512
BASE='acf32d30dd883ed349738e66fb081e85e0d6a3c746f5e3ca169031e8d69ed731'
TARGET='a3733332c2a1b336226bb9000e01665ce54bec970aefc3334b88863b80f40ceb'

def make_plan(old,new):
    require(len(old)==len(new)==SIZE and sha(old)==BASE and sha(new)==TARGET,'不接受其它镜像对')
    fat=FatImage(old)
    def file_sectors(path):
        entry=fat.entries[path]
        left=entry['size']; result=set()
        for offset,length in entry['extents']:
            take=min(length,left)
            if take: result.update(range(offset//SECTOR,(offset+take+SECTOR-1)//SECTOR))
            left-=take
            if not left: break
        require(left==0,'FAT 文件范围不完整')
        return result
    initrd=file_sectors('/boot/initrd.img')
    checksum=file_sectors('/p1chksum')
    require(not initrd&checksum,'目标文件共享扇区')
    changed=[i for i in range(SIZE//SECTOR) if old[i*SECTOR:(i+1)*SECTOR]!=new[i*SECTOR:(i+1)*SECTOR]]
    require(set(changed)<=initrd|checksum,'发现目标容器之外的变化')
    ordered=sorted(set(changed)&initrd)+sorted(set(changed)&checksum)
    rows=[]
    for sector in ordered:
        start=sector*SECTOR
        a,b=old[start:start+SECTOR],new[start:start+SECTOR]
        rows.append({'sector':sector,'offset':start,'bytes':SECTOR,
                     'phase':'checksum' if sector in checksum else 'initrd',
                     'before_sha256':sha(a),'after_sha256':sha(b)})
    return {'schema':'a7r5-kit-trust-plan-v1','device':'/dev/cnflasha1','device_number':'252:129',
            'source_sha256':BASE,'candidate_sha256':TARGET,'partition_bytes':SIZE,
            'changed_bytes':sum(a!=b for a,b in zip(old,new)),
            'logical_sector_size':SECTOR,'changed_sectors':len(rows),'logical_write_bytes':len(rows)*SECTOR,
            'physical_write_amplification_known':False,'rows':rows,
            'barriers':['fsync after initrd sectors','fsync after checksum sectors'],
            'automatic_retry':False,'automatic_rollback':False,'reboot':False}

def classify(raw,old,new,rows):
    require(len(raw)==len(old)==len(new)==SIZE,'恢复前像长度不完整')
    if raw==old: return {'state':'EXACT_ORIGINAL','write_needed':False,'automatic_repair':False}
    if raw==new: return {'state':'EXACT_CANDIDATE','write_needed':False,'automatic_repair':False}
    cursor=0; seen=0
    for row in sorted(rows,key=lambda r:r['offset']):
        offset=row['offset']; end=offset+SECTOR
        require(offset>=cursor and raw[cursor:offset]==old[cursor:offset],'差异扇区外未知变化')
        for got,a,b in zip(raw[offset:end],old[offset:end],new[offset:end]):
            require(got in (a,b),'差异扇区内未知字节')
        cursor=end; seen+=1
    require(seen==258 and raw[cursor:]==old[cursor:],'恢复清单或尾部存在未知变化')
    return {'state':'KNOWN_OLD_NEW_MIXTURE','write_needed':'需另行判断','automatic_repair':False,
            'next':'仅生成新恢复计划；禁止自动套逆补丁'}
