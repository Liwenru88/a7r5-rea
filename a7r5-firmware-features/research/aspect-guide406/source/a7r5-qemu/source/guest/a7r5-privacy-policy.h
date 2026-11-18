/* 仅允许从已知菜单补入未完成的首次提示；查看模式和已确认状态不进入。 */
static int a7r5_privacy_can_open(unsigned int current,unsigned int selecting,unsigned int accepted) {
    return current==0x2d6 && selecting==0 && accepted==0;
}
