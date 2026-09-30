.syntax unified
.cpu arm7tdmi
.thumb
.text
.align 2
.global example_thumb_key
.type example_thumb_key, %function
.thumb_func
/* r0: CKIInput enum. r0 return: CKIEvent. Called from host Thumb naming task. */
example_thumb_key:
    push {r4, lr}
    bl example_key
    pop {r4}
    pop {r1}
    bx r1
.size example_thumb_key, .-example_thumb_key
