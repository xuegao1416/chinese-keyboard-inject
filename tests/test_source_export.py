import tempfile
import unittest
from pathlib import Path
from tools.export_source import export_source

class SourceExportTests(unittest.TestCase):
    def test_bundle_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'bundle'
            result = export_source(out)
            self.assertEqual(result['character_count'], 7168)
            for name in ('cki_keyboard.h', 'cki_keyboard.c', 'cki_text.h', 'example.c', 'example_thumb.s', 'README.md', 'LICENSE'):
                self.assertTrue((out / name).is_file())
            with self.assertRaises(ValueError):
                export_source(out)
    def test_charset_validation(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'chars.json'
            for data in ('[]', '[65535]', '[true]', '["bad"]', '[256, 511]'):
                p.write_text(data)
                with self.assertRaises(ValueError):
                    export_source(Path(d) / 'out', p)
            p.write_text('["0x0100", 513]')
            self.assertEqual(export_source(Path(d) / 'out', p)['character_count'], 2)

    def test_generated_compiles_and_runs(self):
        import shutil
        import subprocess
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root) as directory:
            out = Path(directory) / 'bundle'
            export_source(out)
            bundled = root / 'dist/CKI-18.1.3-win64/toolchain/bin/clang.exe'
            clang = str(bundled) if bundled.exists() else shutil.which('clang')
            self.assertIsNotNone(clang, 'Clang required for ARM validation')
            for name in ('cki_keyboard.c', 'example.c', 'example_thumb.s'):
                flags = [] if name.endswith('.s') else ['-std=c99', '-ffreestanding', '-fno-builtin']
                subprocess.run([clang, '--target=arm-none-eabi', '-march=armv4t', '-mthumb', *flags, '-Wall', '-Wextra', '-Werror', '-c', str(out / name), '-o', str(out / (name + '.o'))], check=True)
            subprocess.run([clang, '--target=arm-none-eabi', '-march=armv4t', '-mthumb', '-nostdlib', '-fuse-ld=lld', '-Wl,-e,example_thumb_key', *[str(out / (n + '.o')) for n in ('cki_keyboard.c', 'example.c', 'example_thumb.s')], '-o', str(out / 'example.elf')], check=True)
            (out / 'runtime.c').write_text('''#include "cki_keyboard.h"
int main(void) {
 unsigned char b[5]={0xBB,0xFF}; CKIConfig c={b,5,3,{0,0},0,0,0}; CKIKeyboard k;
 if(!cki_keyboard_init(&k,&c)||b[0]!=0xBB) return 1;
 if(cki_keyboard_input(&k,CKI_L)!=CKI_CHANGED||k.page!=223) return 2;
 if(cki_keyboard_input(&k,CKI_R)!=CKI_CHANGED||k.page!=0) return 3;
 if(cki_keyboard_input(&k,CKI_LEFT)!=CKI_CHANGED||k.cursor!=7) return 4;
 if(cki_keyboard_input(&k,CKI_RIGHT)!=CKI_CHANGED||k.cursor!=0) return 5;
 if(cki_keyboard_input(&k,CKI_A)!=CKI_CHANGED||b[1]!=1||b[2]!=0||b[3]!=255) return 6;
 if(cki_keyboard_input(&k,CKI_A)!=CKI_REJECTED) return 7;
 if(cki_keyboard_input(&k,CKI_LATIN)!=CKI_EXIT_LATIN||k.active) return 8;
 if(!cki_text_delete(b,5,&c.encoding)||b[1]!=255) return 9;
 if(!cki_keyboard_init(&k,&c)) return 10;
 if(cki_keyboard_input(&k,CKI_UP)!=CKI_CHANGED||k.cursor!=24) return 11;
 return 0;
}''')
            if shutil.which('gcc'):
                prefix = []
                location = str(out)
            else:
                prefix = ['wsl', '-d', 'Ubuntu-24.04', '--']
                location = subprocess.check_output(prefix + ['wslpath', '-a', out.as_posix()], text=True).strip()
            binary = location + '/runtime'
            subprocess.run(prefix + ['gcc', '-std=c99', '-Wall', '-Wextra', '-Werror', location + '/cki_keyboard.c', location + '/runtime.c', '-o', binary], check=True)
            subprocess.run(prefix + [binary], check=True)

    def test_custom_encoding_callbacks_and_invalid_reinit(self):
        import shutil
        import subprocess
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root) as directory:
            d = Path(directory)
            charset = d / 'chars.json'
            charset.write_text('["0x8001", 0, "0x8002"]')
            out = d / 'bundle'
            export_source(out, charset)
            (out / 'runtime.c').write_text('''#include "cki_keyboard.h"
static unsigned int cells, names, selected, seen;
static int lead(unsigned char b, void *context) { return b == *(unsigned char *)context; }
static void draw(void *ctx, unsigned int x, unsigned int y, unsigned short c, int s) {
 (void)ctx; if(x >= 8 || y >= 4) seen=99; ++cells; selected += s;
 if(c==0x8001 || c==0x8002) ++seen;
}
static void name(void *ctx, const unsigned char *b) { (void)ctx; (void)b; ++names; }
int main(void) {
 unsigned char lead_byte=0x80, b[5]={0xFF};
 CKIConfig c={b,5,2,{lead,&lead_byte},draw,name,0}; CKIKeyboard k;
 if(!cki_keyboard_init(&k,&c)) return 1;
 cki_keyboard_render(&k);
 if(cells!=32 || names!=1 || selected!=1 || seen!=2) return 2;
 if(cki_keyboard_input(&k,CKI_A)!=CKI_CHANGED || b[0]!=0x80 || b[1]!=1) return 3;
 if(cki_keyboard_input(&k,CKI_RIGHT)!=CKI_CHANGED) return 4;
 if(cki_keyboard_input(&k,CKI_A)!=CKI_REJECTED || b[2]!=0xFF) return 5;
 if(cki_keyboard_input(&k,CKI_B)!=CKI_CHANGED || b[0]!=0xFF) return 6;
 if(cki_keyboard_input(&k,CKI_L)!=CKI_CHANGED || k.page!=0) return 7;
 b[0]=0x80; b[1]=0xFF;
 if(cki_keyboard_init(&k,&c) || k.active || b[0]!=0x80 || b[1]!=0xFF) return 8;
 if(cki_keyboard_input(&k,CKI_A)!=CKI_REJECTED) return 9;
 return 0;
}''')
            prefix = [] if shutil.which('gcc') else ['wsl', '-d', 'Ubuntu-24.04', '--']
            location = str(out) if not prefix else subprocess.check_output(prefix + ['wslpath', '-a', out.as_posix()], text=True).strip()
            binary = location + '/runtime'
            subprocess.run(prefix + ['gcc', '-std=c99', '-Wall', '-Wextra', '-Werror', location + '/cki_keyboard.c', location + '/runtime.c', '-o', binary], check=True)
            subprocess.run(prefix + [binary], check=True)

if __name__ == '__main__':
    unittest.main()
