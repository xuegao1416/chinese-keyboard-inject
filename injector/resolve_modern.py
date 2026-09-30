from pathlib import Path
import json, argparse
from trampoline import decode_thumb_bl
BASE=0x08000000

def calls(rom,start,span=0x180):
 out=[]
 for q in range(start,min(start+span,len(rom)-4),2):
  v=decode_thumb_bl(rom,q)
  if v is not None: out.append((q,v&~1))
 return out

def callers(rom,target):
 t=target&~1; out=[]
 for q in range(0,len(rom)-4,2):
  v=decode_thumb_bl(rom,q)
  if v is not None and (v&~1)==t: out.append(q)
 return out

def func_start(rom,pos,back=0x80):
 # Thumb GCC functions here begin with PUSH (0xB4xx/0xB5xx). Pick nearest plausible prologue.
 for q in range(pos&~1,max(-1,pos-back),-2):
  h=int.from_bytes(rom[q:q+2],'little')
  if (h&0xFE00)==0xB400: return q
 raise RuntimeError(f'no Thumb prologue before {pos:#x}')

def find_all(b,pat):
 out=[];q=0
 while 1:
  q=b.find(pat,q)
  if q<0:return out
  out.append(q);q+=1

def in_handler_table(rom,fs):
 """True if this function entry appears in a four-slot all-Thumb-pointer table.

 A keyboard key-handler that is reached only through its jump table has no
 direct `BL` caller. Agbcc -Os builds in that shape inline GetChar completely
 and leave one out-of-line copy that only the table reaches; see docs/MATRIX.md
 Sec.4. A literal-scan for the entry's Thumb-tagged address plus the four-slot
 shape test is exactly the identity test already used for the handler table.
 """
 ptr=(BASE+fs+1).to_bytes(4,'little')
 for p in find_all(rom,ptr):
  if p+16>len(rom): continue
  vals=[int.from_bytes(rom[p+i:p+i+4],'little') for i in range(0,16,4)]
  if all(BASE <= (v&~1) < BASE+len(rom) and v&1 for v in vals):
   return True
 return False

def is_thumb_return(h):
 # bx lr / bx rN / POP {...,PC}.  Thumb PUSH=1011-01P-rrrrrrrr, POP=1011-1L-rrrrrrrr.
 return (h & 0xF87F) == 0x4700 or ((h & 0xFC00) == 0xBC00 and h & 0x100)


def pool_word(rom,q):
 """True if the four aligned bytes ending at q are a plausible GBA pointer.

 GCC parks the *previous* function's constant pool immediately before a Thumb
 entry, so "the halfword before the PUSH must be a return" is not the whole
 rule: astral_emerald's KeyboardKeyHandler_Character at 0x1b18e4 is preceded by
 the word 0x08a03168, which is a literal, not code. Reading it as an
 instruction is what made strict_entry walk past the real entry to 0x1b15c0.
 """
 if q < 4 or q % 4: return False
 w=int.from_bytes(rom[q-4:q],'little')
 return (BASE <= w < BASE+len(rom)) or (0x02000000 <= w < 0x03000000)


def is_func_entry(rom,q):
 """q is a function entry: PUSH{...,lr} preceded by a return, a nop, or a pool."""
 if q < 0 or q+2 > len(rom): return False
 h=int.from_bytes(rom[q:q+2],'little')
 if (h&0xFC00)!=0xB400 or not h&0x100: return False
 prev=int.from_bytes(rom[q-2:q],'little')
 return is_thumb_return(prev) or prev in (0x0000,0xBF00) or pool_word(rom,q)


def strict_entry(rom,pos,back=0x800):
 """Real function entry containing pos.

 func_start() accepts the nearest preceding PUSH, but a big key handler contains
 inner `push {r4,r5,lr}` blocks, so on an inlined-GetChar build it stops ~6-0x10
 bytes past the true entry. A true entry is a PUSH{...,lr} whose preceding
 halfword is a return or alignment padding.
 """
 for q in range(pos&~1,max(1,pos-back),-2):
  if is_func_entry(rom,q): return q
 return None



def tables_slot0(rom,entry):
 """4-slot all-Thumb pointer arrays whose FIRST slot is `entry`.

 Distinct targets and four real function entries: naming_screen.o's four key
 handlers sit adjacent in most builds, but adjacency is a layout accident, not
 the identity. astral_emerald spreads Character/Page/Backspace/OK over 0x152C
 (0x1b18e4 / 0x1b0698 / 0x1b1bc4 / 0x1b06c8), which a span window of 0x800
 rejected outright. Requiring each target to be a genuine entry keeps the
 discrimination - a run of four arbitrary pointers into mid-function code is
 still refused - without assuming anything about how the linker ordered them.
 """
 ptr=(BASE+entry+1).to_bytes(4,'little')
 out=[]
 for p in find_all(rom,ptr):
  if p+16>len(rom): continue
  vals=[int.from_bytes(rom[p+i:p+i+4],'little') for i in range(0,16,4)]
  if not all(BASE <= (v&~1) < BASE+len(rom) and v&1 for v in vals): continue
  offs=[(v&~1)-BASE for v in vals]
  if len(set(offs))!=4: continue
  out.append((p,vals))
 return out


# Thumb-1 dispatch arithmetic inside HandleKeyboardEvent: the keyboard-row index
# is scaled by pages*rows and then by columns (`*5`, `*8`), the lock-state byte is
# loaded from [r3,#10], and the sprite array base is dereferenced. Same source +
# same layout compiles to these eight halfwords identically across GCC versions,
# which makes it a stronger identity proof than a literal xref once the handler
# array has been folded into a bigger struct.
DISPATCH_SIG=((0x0082,0xFFFF),(0x1812,0xFFFF),(0x4B00,0xFF00),(0x00D2,0xFFFF),
 (0x189B,0xFFFF),(0x7A98,0xFFFF),(0x4B00,0xFF00),(0x681C,0xFFFF))


def dispatch_shape(rom,table):
 """HandleKeyboardEvent located by its own instruction sequence.

 Only consulted after the literal-xref routes have come up empty, because on
 those builds the array's exact address never appears as a literal anywhere.
 The matched function must also have a constant-pool word at or below `table`,
 which is what ties the shape back to *this* table instead of to any other
 keyboard-shaped code in the ROM. Returns the entry or None.
 """
 hits=[]
 for q in range(0,len(rom)-16,2):
  if int.from_bytes(rom[q:q+2],'little')!=DISPATCH_SIG[0][0]: continue
  if all(int.from_bytes(rom[q+2*i:q+2*i+2],'little')&m==v
         for i,(v,m) in enumerate(DISPATCH_SIG)): hits.append(q)
 ents=[]
 for h in hits:
  try: e=func_start(rom,h,0x300)
  except RuntimeError: continue
  if e not in ents: ents.append(e)
 if len(ents)!=1: return None
 e=ents[0]
 for q in range(e,min(e+0x120,len(rom)-2),2):
  hh=int.from_bytes(rom[q:q+2],'little')
  if hh&0xF800!=0x4800: continue
  lit=((q+4)&~3)+((hh&0xFF)<<2)
  if lit+4>len(rom): continue
  v=int.from_bytes(rom[lit:lit+4],'little')
  if BASE <= v < BASE+len(rom) and 0 <= table-((v&~1)-BASE) <= 0x100: return e
 return None


class InterfaceChanged(RuntimeError):
 """The build replaced the naming-screen input interface, so there is no grid to overlay.

 Distinct from a resolver gap: a gap is a ROM the injector should learn to place, an
 interface change is a ROM whose keyboard is not the one the adapter draws on top of.
 """


# The four symbol-page rows of the stock layout keep their character codes in every
# localisation that leaves the keyboard alone (5,5,6,5 keys), while the two letter
# pages are exactly what a Chinese build rewrites. Matching that four-row tail at
# each candidate row stride therefore measures the grid's column count without
# depending on which characters sit in it. Across the 20 sample ROMs the answer is
# unambiguous: the 17 that keep the stock grid match at stride 8 and no other, the
# four PVPdalao builds match at stride 14 and no other, and the two pinyin-IME builds
# (maplefall, bailan) match no stride at all.
SYMBOL_ROWS=(bytes.fromhex('a1a2a3a4a5'),bytes.fromhex('a6a7a8a9aa'),
             bytes.fromhex('abacb5b6baae'),bytes.fromhex('b0b1b2b3b4'))


def func_extent(rom,entry,cap=0x800):
 """Bytes from a Thumb entry to the next plausible entry - the body length.

 Used only when the classic bound is unavailable: `calls(rom,handle,char-handle)`
 assumes KeyboardKeyHandler_Character is laid out *after* HandleKeyboardEvent,
 which is a link order, not a fact. astral places the handlers ~0xC8000 before
 the dispatcher, making that span negative and the scan silently empty.
 """
 for q in range(entry+2,min(entry+cap,len(rom)-2),2):
  h=int.from_bytes(rom[q:q+2],'little')
  if (h&0xFC00)!=0xB400 or not h&0x100: continue
  if is_thumb_return(int.from_bytes(rom[q-2:q],'little')): return q-entry
 return cap


def struct_member_dispatch(rom,table):

	"""HandleKeyboardEvent when the handler array is a member of a larger struct.

	Modern builds fold `sKeyboardKeyHandlers` into a struct whose base is what the
	constant pool names, so the array's own address appears as a literal nowhere and
	the `table` / `table-4` xref routes find nothing. The code shape is then
	`ldr rT,[pc]` -> base, `lsls rI,#2`, `adds`, `ldr rT,[rT,#d]` with
	`table == base+d`. Matching that pair is exact rather than positional: astral
	reaches its array as `[r3,#0x18]` off 0x08b1e794, 24 bytes into the struct.

	The pc-relative load is decoded (not just searched for) so the base has to be
	the value *this* instruction actually loads; requiring the pair inside one
	function keeps an unrelated `ldr [r,#24]` from counting.
	"""
	ents=[]
	for d in range(4,0x44,4):
		bw=(BASE+table-d).to_bytes(4,'little')
		imm5=d>>2
		for q in range(0,len(rom)-16,2):
			hw=int.from_bytes(rom[q:q+2],'little')
			if (hw&0xF800)!=0x6800 or ((hw>>6)&0x1F)!=imm5: continue
			found=False
			for p in range(max(0,q-16),q,2):
				lh=int.from_bytes(rom[p:p+2],'little')
				if (lh>>11)!=0b01001: continue
				pool=((BASE+p+4)&~2)+(lh&0xFF)*4
				if 0<=pool-BASE<len(rom)-4 and rom[pool-BASE:pool-BASE+4]==bw:
					found=True; break
			if not found: continue
			try: e=func_start(rom,q,0x400)
			except RuntimeError: continue
			if e not in ents: ents.append(e)
	return ents[0] if len(ents)==1 else None


def keyboard_columns(rom,lo=8,hi=40):

 """Row stride of the naming keyboard layout, plus the offsets it was found at.

 Returns (None,[]) when no stride in [lo,hi) matches. That single result cannot
 say *which* of two opposite things happened - the whole grid was reflowed, or
 only the symbol page's characters were swapped while the letter pages stayed a
 stock 4x8 grid - so callers must measure the letter pages before treating
 (None,[]) as an interface change. See the `s is None` branch below.
 """
 for s in range(lo,hi):
  blk=b''.join(r+b'\x00'*(s-len(r)) for r in SYMBOL_ROWS)
  hits=find_all(rom,blk)
  if hits: return s,hits
 return None,[]


def resolve_modern(rom):
 # Stable semantic/data anchor from Emerald naming screen: 3 pages x 4 rows x 8 columns.
 keyboard=bytes.fromhex(
 'd5 d6 d7 d8 d9 da 00 ad db dc dd de df e0 00 b8 e1 e2 e3 e4 e5 e6 e7 00 e8 e9 ea eb ec ed ee 00 '
 'bb bc bd be bf c0 00 ad c1 c2 c3 c4 c5 c6 00 b8 c7 c8 c9 ca cb cc cd 00 ce cf d0 d1 d2 d3 d4 00 '
 'a1 a2 a3 a4 a5 00 00 00 a6 a7 a8 a9 aa 00 00 00 ab ac b5 b6 ba ae 00 00 b0 b1 b2 b3 b4 00 00 00')
 kh=find_all(rom,keyboard)
 if len(kh)!=1:
  if kh: raise RuntimeError(f'keyboard data anchor hits={list(map(hex,kh))}')
  # The stock grid is absent. Say *why*, because the two reasons have opposite
  # consequences: a build whose grid still measures 8 columns is a build the
  # resolver should learn to place, and a build whose grid is wider has replaced
  # the keyboard the 4x8 adapter is drawn on top of.
  s,hits=keyboard_columns(rom)
  where=', '.join(hex(x) for x in hits[:2])
  if s is not None and s!=8:
   raise InterfaceChanged(
    f'naming keyboard grid is 4 rows x {s} columns (layout at {where}), not the '
    f'stock 3 pages x 4 rows x 8 columns - this build replaced the keyboard the '
    f'4x8 Chinese grid overlays, so there is nothing here to inject into')
  if s is None:
   # (None,[]) has two opposite causes and only one of them is a real interface
   # change. At stride 8 a page is its own 32 bytes, so searching the two stock
   # letter pages measures whether the grid the 4x8 Chinese overlay is drawn on
   # top of still stands. If it does, what is missing is our ability to place the
   # layout from the surviving pages - a resolver gap, not something to reject.
   intact=[(p+1,[hex(x) for x in find_all(rom,keyboard[p*32:(p+1)*32])]) for p in (0,1)]
   intact=[(p,h) for p,h in intact if h]
   if intact:
    raise RuntimeError('keyboard data anchor hits=[] and the symbol page matches no row stride '
     f'8..39, but the stock 4x8 letter grid is intact at {intact} - only the symbol page was '
     'rewritten, so the grid the Chinese overlay is drawn on top of still exists and this is '
     'a resolver gap rather than an interface change')
   raise InterfaceChanged(
    'naming keyboard matches neither the stock layout nor the stock symbol pages '
    'at any row stride 8..39, and neither stock letter page is present at stride 8 '
    'either - this build replaced the keyboard the 4x8 Chinese grid overlays, so '
    'there is nothing here to inject into')
  raise RuntimeError('keyboard data anchor hits=[] but the grid still measures '
    '8 columns, so this is a resolver gap rather than an interface change')
 kb=kh[0]
 # The keyboard address may occur in multiple literal pools after modern GCC inlining.
 # Decode actual Thumb LDR-literal users and select the callable helper rather than
 # requiring a unique raw 32-bit pointer occurrence.
 ldr_users=[]
 target=BASE+kb
 for q in range(0,len(rom)-2,2):
  h=int.from_bytes(rom[q:q+2],'little')
  if h&0xF800==0x4800:
   lit=((q+4)&~3)+((h&0xff)<<2)
   if lit+4<=len(rom) and int.from_bytes(rom[lit:lit+4],'little')==target:
    try: fs=func_start(rom,q,0x200)
    except RuntimeError: continue
    ldr_users.append((q,lit,fs,callers(rom,BASE+fs)))
 # De-duplicate by containing function. A standalone GetChar helper has a direct
 # caller; an inlined duplicate in PrintKeyboardKeys/other rendering code does not.
 funcs={}
 for q,lit,fs,cs in ldr_users: funcs.setdefault(fs,{'refs':[],'callers':cs})['refs'].append(q)
 callable_funcs=[fs for fs,x in funcs.items() if x['callers']]
 if len(callable_funcs)==1:
  getchar=callable_funcs[0]
 elif len(funcs)==1:
  # A single candidate is unambiguous: whichever function reads the keyboard
  # data block is the lookup, callers or not. Some agbcc -Os builds fully inline
  # GetChar and leave the one out-of-line copy reachable only through the
  # key-handler jump table, so `callers == []`; docs/MATRIX.md Sec.4.
  getchar=next(iter(funcs))
 else:
  # Several candidates: prefer one that is an entry of a four-slot
  # all-Thumb-pointer table (i.e. a keyboard key handler reached only through
  # its jump table), which is stronger evidence than a direct caller.
  tabled=[fs for fs in funcs if in_handler_table(rom,fs)]
  if len(tabled)==1:
   getchar=tabled[0]
  else:
   raise RuntimeError('keyboard LDR dataflow candidates='+repr({hex(k):{'refs':list(map(hex,v['refs'])),'callers':list(map(hex,v['callers']))} for k,v in funcs.items()}))
 c_getchar=funcs[getchar]['callers']
 forced=None
 getchar_repaired=False
 if len(c_getchar)==0:
  # Agbcc -Os inlines GetChar into the Character key handler and reaches that
  # handler only through its four-slot jump table, so nothing BLs it. The LDR
  # user is then the handler itself; see docs/MATRIX.md Sec.4. Require the
  # table membership here so the step cannot accept an arbitrary leaf; the
  # handler-table derivation below re-checks it independently.
  if in_handler_table(rom,getchar):
   char=getchar
   addchar=None
   addchar_inlined=True
  else:
   # Modern pokeemerald-expansion renames it GetCharAtKeyboardPos(s16,s16) and
   # -Os inlines it into KeyboardKeyHandler_Character, so nothing BLs it and the
   # address func_start produced is an inner `push`, not the table entry. Re-derive
   # the entry from each keyboard LDR site and require exactly one four-slot array
   # that starts with it, in the same .rodata neighbourhood as the keyboard block.
   # LightPlatinum/rhcn/bubble128/exmingyan/pokedelphia all put that array at
   # keyboard_data-0x10; astral_emerald keeps the same source layout but its
   # .rodata is 1.1 MB wide, so the array sits 0x11b54c from the keyboard block.
   # Proximity therefore stays a preference: use it to break ties, never to
   # reject. A far table is still reported separately so the weaker route is
   # visible in the JSON instead of looking like the normal one.
   near,far={},{}
   table_route='keyboard_neighbourhood'
   for fs,x in funcs.items():
    for q in x['refs']:
     e=strict_entry(rom,q)
     if e is None: continue
     for p,vals in tables_slot0(rom,e):
      (near if abs(p-kb)<=0x2000 else far).setdefault(p,vals)
   if near:
    cands=near
   elif len(far)==1:
    cands=far; table_route='far_rodata'
   else:
    cands=far
   if len(cands)!=1:
    raise RuntimeError(
     f'GetChar has no caller and is not a key-handler table entry: 0x{getchar:x}; '
     f'strict-entry repair candidates={list(map(hex,cands))} '
     f'(near={list(map(hex,near))} far={list(map(hex,far))})')

   table,vals=next(iter(cands.items()))
   forced=(table,vals)
   char=getchar=(vals[0]&~1)-BASE
   getchar_repaired=True
   addchar=None
   addchar_inlined=True
 elif len(c_getchar)==1:
  addchar=func_start(rom,c_getchar[0],0x200)
  c_add=callers(rom,BASE+addchar)
  if len(c_add)==1:
   char=func_start(rom,c_add[0],0x200)
   addchar_inlined=False
  elif len(c_add)==0:
   # Modern GCC can inline AddTextCharacter into KeyboardKeyHandler_Character.
   # In that shape the function containing the GetChar call is itself the handler.
   char=addchar
   addchar=None
   addchar_inlined=True
  else:
   raise RuntimeError(f'AddTextCharacter callers={list(map(hex,c_add))}')
 else:
  raise RuntimeError(f'GetChar callers={list(map(hex,c_getchar))}')
 # Handler table is a stronger relation than assuming adjacency.
 if forced is None:
  charptr=(BASE+char+1).to_bytes(4,'little')
  th=find_all(rom,charptr)
  tables=[]
  for p in th:
   if p+16<=len(rom):
    vals=[int.from_bytes(rom[p+i:p+i+4],'little') for i in range(0,16,4)]
    if all(BASE <= (v&~1) < BASE+len(rom) and v&1 for v in vals): tables.append((p,vals))
  if len(tables)!=1: raise RuntimeError(f'handler tables={[(hex(p),list(map(hex,v))) for p,v in tables]}')
  table,vals=tables[0]
 char,page,back,ok=[(v&~1)-BASE for v in vals]
 # HandleKeyboardEvent loads the handler table; its literal xref lands inside the function.
 tx=find_all(rom,(BASE+table).to_bytes(4,'little'))
 fns=[]
 handle_via='table_literal'
 if len(tx)==1:
  handle=func_start(rom,tx[0],0x300)
 elif len(tx)==0:
  # Some builds address the table through a pointer to the word just before it
  # (a struct whose first member precedes the table), so no exact literal
  # exists. Widen by one word, then require the referencing code to live in a
  # single function - otherwise fall through to the dispatch shape.
  near=find_all(rom,(BASE+table-4).to_bytes(4,'little'))
  for x in near:
   try: fs=func_start(rom,x,0x300)
   except RuntimeError: continue
   if fs not in fns: fns.append(fs)
  if len(fns)==1:
   handle=fns[0]; handle_via='table_minus4_literal'
  else:
   # Modern expansion keeps the array inside a larger struct, so the pool only
   # names that struct's base and the array has no xref at all. Identify the
   # dispatcher by what it does instead of by who points at the table.
   handle=dispatch_shape(rom,table); handle_via='dispatch_shape'
   if handle is None:
    handle=struct_member_dispatch(rom,table); handle_via='struct_member_dispatch'

 else:
  raise RuntimeError(f'handler table xrefs={list(map(hex,tx))}')
 if handle is None:
  raise RuntimeError(
   f'handler table @{hex(BASE+table)} has no exact literal xref, table-4 is '
   f'referenced from {len(fns)} functions {list(map(hex,fns))}, and the '
   f'HandleKeyboardEvent dispatch shape did not resolve uniquely - ambiguous')
 frame_span=char-handle if char>handle else func_extent(rom,handle)
 hc=calls(rom,handle,frame_span); bc=calls(rom,back,0x50)

 common=set(v for _,v in hc)&set(v for _,v in bc)
 common2=[v for v in common if len(callers(rom,v))==2]
 if len(common2)!=1: raise RuntimeError(f'delete intersection={list(map(hex,common))}, two-caller={list(map(hex,common2))}')
 delete=common2[0]-BASE
 # Cursor resolver supports both shapes: classic code has MoveCursorToOKButton
 # as the final non-delete internal helper and that helper calls SetCursorPos;
 # modern GCC may inline MoveCursorToOKButton, exposing SetCursorPos as a leaf.
 internal=[v for _,v in hc if BASE <= v < BASE+len(rom) and v != BASE+delete]
 # `cursor` is reported but not used by 1.0: the adapter drives the cursor
 # through its own ck_set_cursor and the real patch sites come from
 # cursor_resolver.py. On the validated host this heuristic mis-resolves to
 # gflib/random.o's Random anyway, and on another build it could also raise on
 # ambiguity. Keep the value (report compatibility) but make the step
 # non-fatal, so it can never block a resolution that does not need it.
 # docs/HOOKS.md Sec.4.
 cursor=None
 try:
  for v in reversed(internal):
   nested=[x for _,x in calls(rom,v-BASE,0x40) if BASE <= x < BASE+len(rom)]
   if nested:
    leaf=[x for x in nested if not calls(rom,x-BASE,0x40)]
    if leaf:
     cursor=min(leaf,key=lambda x:len(callers(rom,x)))-BASE; break
  if cursor is None:
   cursor_candidates=[]
   for v in internal:
    off=v-BASE; cc=len(callers(rom,v)); direct=calls(rom,off,0x50)
    if not direct and 2 <= cc <= 10: cursor_candidates.append((abs(cc-5),off))
   if len(cursor_candidates)==1:
    cursor=cursor_candidates[0][1]
 except Exception:      # noqa: BLE001 - diagnostic field only, never fatal
  cursor=None
 frame=callers(rom,BASE+handle)
 if not frame: raise RuntimeError('Handle callers=[]')
 if len(frame)>1:
  # Task_NamingScreen calls HandleKeyboardEvent immediately near its entry;
  # initialization/state functions call it deeper in a larger routine.
  scored=[]
  for c in frame:
   try: fs=func_start(rom,c,0x300); scored.append((c-fs,c))
   except RuntimeError: pass
  if not scored: raise RuntimeError(f'Handle callers={list(map(hex,frame))}')
  frame=[min(scored)[1]]
 # BufferCharacter is the sole direct callee of AddTextCharacter that contains STRB and returns quickly.
 ac=calls(rom,addchar,0x80) if addchar is not None else calls(rom,char,0x100)
 buffer_candidates=[]
 for _,v in ac:
  off=v-BASE
  if 0<=off<len(rom):
   chunk=rom[off:off+0x40]
   if any((int.from_bytes(chunk[i:i+2],'little')&0xF800)==0x7000 for i in range(0,len(chunk)-1,2)):
    buffer_candidates.append(off)
 # In modern pret layout GetChar is also called; choose the small STRB helper, i.e. shortest to BX/POP return.
 buffer=min(buffer_candidates,key=lambda x: next((i for i in range(0,0x40,2) if int.from_bytes(rom[x+i:x+i+2],'little') in (0x4770,0x4708)),0x40)) if buffer_candidates else None
 # sNamingScreen global is recoverable from repeated LDR-literal values in this cluster. Count EWRAM literals.
 # The cluster is "HandleKeyboardEvent through the end of the key handlers", but
 # that only describes a contiguous range when the handlers are linked after the
 # dispatcher. astral links them 0xC8000 earlier, so a single handle->char window
 # is empty and no EWRAM literal is ever seen. Fall back to the two islands.
 _clus_end=(addchar if addchar is not None else char)
 def cluster(back,fwd):
  if _clus_end>handle:
   return list(range(max(0,handle-back),min(_clus_end+fwd,len(rom)-4),2))
  return (list(range(max(0,handle-back),min(handle+func_extent(rom,handle)+back,len(rom)-4),2))
          +list(range(max(0,_clus_end-back),min(_clus_end+fwd,len(rom)-4),2)))
 ew={}
 for q in cluster(0x100,0x300):
  h=int.from_bytes(rom[q:q+2],'little')
  if h&0xF800==0x4800:
   lit=((q+4)&~3)+((h&0xff)<<2)
   if lit+4<=len(rom):
    v=int.from_bytes(rom[lit:lit+4],'little')
    if 0x02000000<=v<0x02040000: ew[v]=ew.get(v,0)+1

 # Distinguish pointer globals from direct arrays by use, not frequency.
 # sNamingScreen is loaded from EWRAM and immediately dereferenced (LDR Rx,[Rx,#0]);
 # gSprites is a direct array base and is consumed by index/address arithmetic.
 ptr_use={k:0 for k in ew}; direct_use={k:0 for k in ew}
 for q in cluster(0x180,0x380):

  h=int.from_bytes(rom[q:q+2],'little')
  if h&0xF800!=0x4800: continue
  rd=(h>>8)&7; lit=((q+4)&~3)+((h&0xff)<<2)
  if lit+4>len(rom): continue
  v=int.from_bytes(rom[lit:lit+4],'little')
  if v not in ew: continue
  n=int.from_bytes(rom[q+2:q+4],'little')
  # Thumb LDR Rd,[Rb,#imm5*4], imm=0 and Rb == literal destination.
  if (n&0xF800)==0x6800 and ((n>>6)&0x1f)==0 and ((n>>3)&7)==rd:
   ptr_use[v]+=1
  else:
   direct_use[v]+=1
 ns=max(ew,key=lambda k:(ptr_use[k],ew[k],-direct_use[k])) if ew else None
 sprite_candidates=[k for k in ew if k!=ns]
 sprites=max(sprite_candidates,key=lambda k:(direct_use[k],ew[k],-ptr_use[k])) if sprite_candidates else None
 return {'family':'modern-dataflow-v39','handle_via':handle_via,'addchar_inlined':addchar_inlined,'getchar_repaired':getchar_repaired,'keyboard_data':kb,'getchar':getchar,'addchar':addchar,'bufferchar':buffer,'character':char,'page':page,'backspace':back,'ok':ok,'handler_table':table,'handle':handle,'delete':delete,'cursor':cursor,'flash':(next(v for _,v in calls(rom,char,0x20) if len(callers(rom,v))>=4)-BASE),'lr_frame':frame[0],'naming_screen_global':ns,'sprites_global':sprites,'ewram_literal_counts':{hex(k):v for k,v in sorted(ew.items(),key=lambda x:-x[1])[:8]},'ewram_use_semantics':{hex(k):{'ptr_deref':ptr_use[k],'direct':direct_use[k]} for k in ew}}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('rom');ap.add_argument('-o','--output');a=ap.parse_args();p=Path(a.rom);r=resolve_modern(p.read_bytes());
 out={k:(hex(v) if isinstance(v,int) else v) for k,v in r.items()};print(json.dumps(out,indent=2,ensure_ascii=False));
 if a.output:Path(a.output).write_text(json.dumps(out,indent=2,ensure_ascii=False),encoding='utf-8')
if __name__=='__main__':main()
