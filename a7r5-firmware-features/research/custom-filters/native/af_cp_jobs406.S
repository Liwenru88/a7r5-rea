/* work与completion均为运行期消息/BSS指针；不另改三个原worker入口。 */
.syntax unified
.thumb
.section .text.af_cp_jobs406,"ax",%progbits
.global af_cp_jobs406_worker2
.type af_cp_jobs406_worker2,%function
.thumb_func
af_cp_jobs406_worker2:
 movs r0,#2
 b.w af_cp_jobs406_worker_target
.global af_cp_jobs406_worker3
.type af_cp_jobs406_worker3,%function
.thumb_func
af_cp_jobs406_worker3:
 movs r0,#3
 b.w af_cp_jobs406_worker_target
.global af_cp_jobs406_worker6
.type af_cp_jobs406_worker6,%function
.thumb_func
af_cp_jobs406_worker6:
 movs r0,#6
 b.w af_cp_jobs406_worker_target
.global af_cp_jobs406_completion
.type af_cp_jobs406_completion,%function
.thumb_func
af_cp_jobs406_completion:
 mov r1,lr
 b.w af_cp_jobs406_completion_target
.global af_cp_jobs406_invoke_native
.type af_cp_jobs406_invoke_native,%function
.thumb_func
af_cp_jobs406_invoke_native:
 push {r4,lr}
 blx r0
.global af_cp_jobs406_after_native
.type af_cp_jobs406_after_native,%function
.thumb_func
af_cp_jobs406_after_native:
 pop {r4,pc}
.size af_cp_jobs406_invoke_native,.-af_cp_jobs406_invoke_native
