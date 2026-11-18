/* 仅供隔离资源机核对五条保护指令；不是机身部署入口。 */
.text
.global af_resource_map_guard
.type af_resource_map_guard, %function
af_resource_map_guard:
    cbz x0, .Lfailed
    cmn x0, #1
    b.ne .Lready
.Lfailed:
    b af_resource_map_failed
.Lready:
    b af_resource_map_ready
.size af_resource_map_guard, .-af_resource_map_guard
