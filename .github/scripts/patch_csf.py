#!/usr/bin/env python3
"""Enable CSF architectures (10 = G710/most, 12 = Immortalis-G925) for kbase builds."""
import re, sys

def pad(text, col=79):
    return text.ljust(col) + '\\'

def patch_macros(path):
    lines = open(path).read().split('\n')
    if any('case 12:' in l for l in lines):
        print('macros: already patched')
        return
    out = []
    i = 0
    n_inserted = 0
    while i < len(lines):
        out.append(lines[i])
        # detect a "case 9:" line inside a macro switch
        if re.match(r'^\s+case 9:\s*\\?$', lines[i]) and i + 2 < len(lines):
            case_ln = lines[i]
            call_ln = lines[i + 1]
            break_ln = lines[i + 2]
            if 'v9' in call_ln and break_ln.strip().startswith('break;'):
                out.append(call_ln)
                out.append(break_ln)
                for arch in ('10', '12'):
                    out.append(case_ln.replace('case 9', 'case ' + arch))
                    out.append(call_ln.replace('v9', 'v' + arch))
                    out.append(break_ln)
                i += 3
                n_inserted += 1
                continue
        i += 1
    open(path, 'w').write('\n'.join(out))
    print('macros: inserted into %d switch(es)' % n_inserted)

def patch_meson(path):
    s = open(path).read()
    if '[6, 7, 9, 10, 12]' in s:
        print('meson: already patched')
        return
    s2 = s.replace('foreach arch : [6, 7, 9]', 'foreach arch : [6, 7, 9, 10, 12]')
    open(path, 'w').write(s2)
    print('meson: patched' if s2 != s else 'meson: PATTERN NOT FOUND')

patch_meson('src/panfrost/vulkan/meson.build')
patch_macros('src/panfrost/vulkan/panvk_macros.h')

# --- arch 推导兜底 + 诊断 ---
def patch_pan_arch(path):
    s = open(path).read()
    if 'MTK_KBASE_ARCH_FALLBACK' in s:
        print('pan_model.h: already patched')
        return
    old = '''   default:
      return PAN_ARCH_MAJOR(gpu_id);
   }
}'''
    new = '''   default:
      break;
   }

   unsigned arch = PAN_ARCH_MAJOR(gpu_id);
   /* MTK_KBASE_ARCH_FALLBACK: kbase on MT6991 reports a legacy-format gpu_id,
    * arch major encodes to 0. Map by product id instead. */
   if (arch == 0 || arch == 15) {
      unsigned prod = MIDGARD_PROD_ID(gpu_id);
      if (prod == 0x0d08 || prod == 0x0d00)
         arch = 12;
      fprintf(stderr, "PANVK-DEBUG: gpu_id=0x%08llx prod=0x%04x -> arch=%u\\n",
              (unsigned long long)gpu_id, prod, arch);
   }
   return arch;
}'''
    if old not in s:
        print('pan_model.h: PATTERN NOT FOUND')
        return
    s = s.replace(old, new, 1)
    if '#include <stdio.h>' not in s:
        s = s.replace('#define PAN_ARCH_MAJOR', '#include <stdio.h>\n\n#define PAN_ARCH_MAJOR', 1)
    open(path, 'w').write(s)
    print('pan_model.h: patched')

patch_pan_arch('src/panfrost/model/pan_model.h')

# --- 强制 arch 兜底（诊断 + 强制 12）---
def patch_force_arch(path):
    s = open(path).read()
    if 'PANVK_FORCE_ARCH' in s:
        print('physical_device.c: already patched'); return
    old = '   unsigned arch = pan_arch(device->kmod.dev->props.gpu_id);'
    new = '''   unsigned arch = pan_arch(device->kmod.dev->props.gpu_id);
   /* PANVK_FORCE_ARCH */
   fprintf(stderr, "PANVK-DEBUG: arch=%u gpu_id=0x%08llx prod=0x%04x\\n", arch,
           (unsigned long long)device->kmod.dev->props.gpu_id,
           (unsigned)((device->kmod.dev->props.gpu_id >> 16) & 0xffff));
   if (arch != 6 && arch != 7 && arch != 9 && arch != 10 && arch != 12) {
      fprintf(stderr, "PANVK-DEBUG: forcing arch 12\\n");
      arch = 12;
   }'''
    n = s.count(old)
    if n == 0:
        print('physical_device.c: PATTERN NOT FOUND'); return
    s = s.replace(old, new)
    if '#include <stdio.h>' not in s:
        s = s.replace('#include <stdint.h>', '#include <stdint.h>\n#include <stdio.h>', 1)
    open(path, 'w').write(s)
    print('physical_device.c: patched, %d sites' % n)

patch_force_arch('src/panfrost/vulkan/panvk_physical_device.c')

# --- 宏内 arch 归一化：未知 arch 一律按 12 ---
def patch_macro_normalize(path):
    s = open(path).read()
    if 'PANVK_ARCH_NORMALIZE' in s:
        print('macros: already patched'); return
    old = '      switch (arch) {'
    new = '      switch (PANVK_ARCH_NORMALIZE(arch)) {'
    n = s.count(old)
    if n == 0:
        print('macros: PATTERN NOT FOUND'); return
    s = s.replace(old, new)
    helper = '''#define PANVK_ARCH_NORMALIZE(a)                                                \\
   (((a) == 6 || (a) == 7 || (a) == 9 || (a) == 10 || (a) == 12) ? (a) : 12)

'''
    s = s.replace('#define panvk_arch_dispatch(', helper + '#define panvk_arch_dispatch(', 1)
    open(path, 'w').write(s)
    print('macros: normalized %d switches' % n)

patch_macro_normalize('src/panfrost/vulkan/panvk_macros.h')
