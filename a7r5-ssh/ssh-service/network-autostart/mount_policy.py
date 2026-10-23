"""复用已由实机叠加挂载记录回归验证的只读视图校验。"""
import re

def validate_mounts(raw,op):
    """只接受已验证服务的VFAT底层、私有tmpfs及只读账户绑定关系。"""
    rows={};points={}
    def path_text(value):
        escapes={'040':' ','011':'\t','012':'\n','134':'\\'}
        if re.search(r'\\(?!040|011|012|134)',value):raise ValueError('挂载路径转义不符')
        return re.sub(r'\\(040|011|012|134)',lambda m:escapes[m[1]],value)
    try:
        for line in raw.decode('ascii').splitlines():
            before,after=line.split(' - ',1);cols=before.split();fs=after.split()
            if len(cols)<6 or len(fs)!=3:raise ValueError('挂载记录字段不完整')
            if any(not re.fullmatch(r'[1-9][0-9]*',v) for v in cols[:2]):raise ValueError('挂载ID不符')
            mid,parent=map(int,cols[:2])
            if mid in rows or mid==parent or not re.fullmatch(r'[0-9]+:[0-9]+',cols[2]):raise ValueError('挂载ID或设备号重复/不符')
            row=dict(id=mid,parent=parent,device=cols[2],root=path_text(cols[3]),point=path_text(cols[4]),
                     flags=set(cols[5].split(',')),optional=cols[6:],fstype=fs[0],source=fs[1],superflags=set(fs[2].split(',')))
            if not row['point'].startswith('/') or not row['root'].startswith('/'):raise ValueError('挂载路径不是绝对路径')
            rows[mid]=row;points.setdefault(row['point'],[]).append(row)
    except (UnicodeDecodeError,IndexError) as error:raise ValueError('挂载记录格式不符') from error
    def one(point):
        found=points.get(point,[])
        if len(found)!=1:raise ValueError('挂载缺失或重复：'+point)
        return found[0]
    def access(row,mode):return row['flags']&{'ro','rw'}=={mode} and row['superflags']&{'ro','rw'}=={'rw'}
    def base_vfat(row):return row['root']=='/' and row['fstype']=='vfat' and row['source']=='/dev/nflasha10' and access(row,'rw')
    etc=one('/etc');network=one('/tmp_network');account=one('/etc/passwd')
    original=[r for r in points.get('/var',[]) if r['fstype']=='vfat']
    private=[r for r in points.get('/var',[]) if r['fstype']=='tmpfs']
    if len(points.get('/var',[]))!=2 or len(original)!=1 or len(private)!=1:raise ValueError('/var不是已知的两层挂载')
    lower,upper=original[0],private[0]
    if not base_vfat(etc) or not base_vfat(lower):raise ValueError('配置分区或/var底层不符')
    if lower['device']!=etc['device'] or lower['parent']!=etc['parent']:raise ValueError('/var底层与/etc来源关系不符')
    if upper['parent']!=lower['id'] or upper['root']!='/' or upper['fstype']!='tmpfs' or upper['source']!='a7r5-private-ssh':raise ValueError('/var私有挂载父子关系或来源不符')
    if not upper['device'].startswith('0:') or upper['device']==lower['device'] or not access(upper,'rw') or not {'nosuid','nodev'}<=upper['flags']:raise ValueError('/var私有tmpfs属性不符')
    if network['root']!='/' or network['fstype']!='tmpfs' or network['source']!='none' or not network['device'].startswith('0:') or network['device']==upper['device'] or network['parent']!=etc['parent'] or not access(network,'rw'):raise ValueError('/tmp_network不是已知独立tmpfs')
    expected=op['private_source'].removeprefix('/var')+'/passwd.view'
    if account['parent']!=etc['id'] or account['root']!=expected or account['device']!=upper['device'] or account['fstype']!='tmpfs' or account['source']!='a7r5-private-ssh' or not access(account,'ro'):raise ValueError('私有账户只读绑定关系不符')
    # 关键树不接受额外遮蔽挂载；/dev/pts叠加位于该范围外，保持原有处理。
    allowed={'/etc','/etc/passwd','/var','/tmp_network'}
    for row in rows.values():
        point=row['point']
        if any(point==p or point.startswith(p+'/') for p in ('/etc','/var','/tmp_network')):
            if point not in allowed or row['optional']:raise ValueError('关键路径存在未知子挂载或传播属性')
    return dict(policy='private-var-stack-v2',etc_mount_id=etc['id'],var_lower_id=lower['id'],var_private_id=upper['id'],
                account_bind_id=account['id'],network_mount_id=network['id'],var_parent_chain_verified=True,account_readonly_bind_verified=True)
