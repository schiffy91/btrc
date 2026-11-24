#include "Keymap.h"
#include "../../Shim/Shim.h"

#include <ctype.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>

typedef struct { const char *start; size_t size; } Token;
typedef struct { const char *cursor; const char *end; } Lexer;
typedef struct {
    Token name;
    uint32_t code;
    uint32_t levels[4][8];
    int repeat;
} Key;

struct BtrcWaylandKeymap {
    size_t count;
    size_t capacity;
    Key *keys;
};

/* A compositor sends a compiled XKB keymap. Read names and symbols from
 * that mapping; virtual and physical keyboards need not share keycodes. */
static Token next(Lexer *l) {
    while (l->cursor < l->end) {
        if (isspace((unsigned char)*l->cursor)) { l->cursor++; continue; }
        if (*l->cursor == '#' || (l->end-l->cursor >= 2 && l->cursor[0] == '/' && l->cursor[1] == '/')) {
            while (l->cursor < l->end && *l->cursor != '\n') { l->cursor++; }
            continue;
        }
        if (l->end-l->cursor >= 2 && l->cursor[0] == '/' && l->cursor[1] == '*') {
            l->cursor += 2;
            while (l->end-l->cursor >= 2 && !(l->cursor[0] == '*' && l->cursor[1] == '/')) { l->cursor++; }
            if (l->end-l->cursor >= 2) { l->cursor += 2; } else { l->cursor = l->end; }
            continue;
        }
        break;
    }
    if (l->cursor == l->end) { return (Token){0}; }
    const char *start = l->cursor++;
    if (*start == '"') {
        while (l->cursor < l->end && *l->cursor != '"') {
            if (*l->cursor++ == '\\' && l->cursor < l->end) { l->cursor++; }
        }
        if (l->cursor < l->end) { l->cursor++; }
    } else if (*start == '<') {
        while (l->cursor < l->end && *l->cursor != '>') { l->cursor++; }
        if (l->cursor < l->end) { l->cursor++; }
    } else if (isalnum((unsigned char)*start) || *start == '_') {
        while (l->cursor < l->end && (isalnum((unsigned char)*l->cursor) || *l->cursor == '_')) { l->cursor++; }
    }
    return (Token){start, (size_t)(l->cursor-start)};
}

static bool is(Token t, const char *s) { return t.size == strlen(s) && !memcmp(t.start, s, t.size); }

static bool number(Token t, unsigned base, uint32_t *value) {
    if (!t.size) { return false; }
    uint32_t n = 0;
    for (size_t i = 0; i < t.size; i++) {
        unsigned char c = (unsigned char)t.start[i];
        unsigned digit;
        if (c >= '0' && c <= '9') { digit = (unsigned)(c - '0'); }
        else if (c >= 'a' && c <= 'f') { digit = (unsigned)(c - 'a') + 10u; }
        else if (c >= 'A' && c <= 'F') { digit = (unsigned)(c - 'A') + 10u; }
        else { return false; }
        if (digit >= base || n > (UINT32_MAX-digit)/base) { return false; }
        n = n*base + digit;
    }
    *value = n;
    return true;
}

typedef struct { const char *name; uint32_t symbol; } Named;

/* These names and values are the XKB wire keysyms. Printable Unicode can
 * also be spelled Uxxxx or as the hexadecimal keysym 0x0100xxxx. */
static const Named names[] = {
    {"space",' '},{"exclam",'!'},{"quotedbl",'"'},{"numbersign",'#'},{"dollar",'$'},{"percent",'%'},
    {"ampersand",'&'},{"apostrophe",'\''},{"quoteright",'\''},{"parenleft",'('},{"parenright",')'},{"asterisk",'*'},
    {"plus",'+'},{"comma",','},{"minus",'-'},{"period",'.'},{"slash",'/'},{"colon",':'},{"semicolon",';'},
    {"less",'<'},{"equal",'='},{"greater",'>'},{"question",'?'},{"at",'@'},{"bracketleft",'['},
    {"backslash",'\\'},{"bracketright",']'},{"asciicircum",'^'},{"underscore",'_'},{"grave",'`'},
    {"braceleft",'{'},{"bar",'|'},{"braceright",'}'},{"asciitilde",'~'},{"nobreakspace",0xa0},
    {"sterling",0xa3},{"EuroSign",0x20ac},{"copyright",0xa9},{"section",0xa7},{"degree",0xb0},
    {"adiaeresis",0xe4},{"odiaeresis",0xf6},{"udiaeresis",0xfc},{"ssharp",0xdf},
    {"agrave",0xe0},{"acircumflex",0xe2},{"ccedilla",0xe7},{"egrave",0xe8},{"eacute",0xe9},
    {"ecircumflex",0xea},{"ugrave",0xf9},{"Adiaeresis",0xc4},{"Odiaeresis",0xd6},{"Udiaeresis",0xdc},
    {"Escape",0xff1b},{"Return",0xff0d},{"KP_Enter",0xff8d},{"Left",0xff51},{"Up",0xff52},
    {"Right",0xff53},{"Down",0xff54},{"Tab",0xff09},{"ISO_Left_Tab",0xfe20},{"BackSpace",0xff08},
    {"Delete",0xffff},{"Home",0xff50},{"End",0xff57},{"Shift_L",0xffe1},{"Shift_R",0xffe2},
    {"Alt_L",0xffe9},{"Alt_R",0xffea}
};

static uint32_t symbol(Token t) {
    if (t.size == 1 && (unsigned char)t.start[0] < 128) { return (unsigned char)t.start[0]; }
    uint32_t value;
    if (t.size >= 3 && t.start[0] == '0' && t.start[1] == 'x' && number((Token){t.start+2,t.size-2},16,&value)) { return value; }
    if (t.size >= 5 && t.start[0] == 'U' && number((Token){t.start+1,t.size-1},16,&value) && value <= 0x10ffff) {
        return value < 256 ? value : 0x01000000u | value;
    }
    for (size_t i = 0; i < sizeof(names)/sizeof(names[0]); i++) { if (is(t,names[i].name)) { return names[i].symbol; } }
    return 0;
}

static Key *keyNamed(BtrcWaylandKeymap *map, Token name) {
    for (size_t i = 0; i < map->count; i++) {
        if (map->keys[i].name.size == name.size && !memcmp(map->keys[i].name.start,name.start,name.size)) { return &map->keys[i]; }
    }
    return NULL;
}

static bool addKey(BtrcWaylandKeymap *m, Token name, uint32_t code) {
    if (code < 8 || code > 0xffff) { return true; }
    if (m->count == m->capacity) {
        size_t capacity = m->capacity ? m->capacity * 2 : 128;
        if (capacity > 65536) { return false; }
        Key *keys = realloc(m->keys,capacity*sizeof(*keys));
        if (!keys) { return false; }
        m->keys = keys;
        m->capacity = capacity;
    }
    m->keys[m->count++] = (Key){.name=name,.code=code};
    return true;
}

static void readSymbols(Lexer *l, Key *key) {
    unsigned group = 0;
    unsigned depth = 1;
    while (depth) {
        Token t = next(l);
        if (!t.size) { return; }
        if (is(t,"{")) { depth++; continue; }
        if (is(t,"}")) { depth--; continue; }
        if (depth != 1) { continue; }
        if (is(t,"repeat")) {
            if (is(next(l),"=")) {
                Token value = next(l);
                if (key) {
                    if (is(value,"Yes") || is(value,"True") || is(value,"true")) { key->repeat = 1; }
                    if (is(value,"No") || is(value,"False") || is(value,"false")) { key->repeat = -1; }
                }
            }
            continue;
        }
        if (!is(t,"[")) { continue; }
        Lexer look = *l;
        Token first = next(&look);
        if (first.size == 6 && !memcmp(first.start, "Group", 5) && first.start[5] >= '1' && first.start[5] <= '4') {
            /* A group selector in type[GroupN] or symbols[GroupN]. */
            group = (unsigned)(first.start[5]-'1');
            while ((t = next(l)).size && !is(t,"]")) { }
            continue;
        }
        unsigned level = 0;
        while ((t = next(l)).size && !is(t,"]")) {
            if (is(t,",")) { continue; }
            if (key && group < 4 && level < 8) { key->levels[group][level] = symbol(t); }
            ++level;
        }
        ++group;
    }
}

BtrcWaylandKeymap *btrcWaylandKeymapRead(int fd, size_t size) {
    struct stat st;
    if (!size || size > 16u*1024u*1024u || fstat(fd,&st) || st.st_size < 0 || (uint64_t)st.st_size < size) { return NULL; }
    char *data = mmap(NULL,size,PROT_READ,MAP_PRIVATE,fd,0);
    if (data == MAP_FAILED) { return NULL; }
    BtrcWaylandKeymap *map = calloc(1,sizeof(*map));
    bool valid = map && data[size-1] == 0;
    Lexer l = {data,data+size-1};
    bool codes = false;
    bool symbols = false;
    Token t;
    while (valid && (t = next(&l)).size) {
        if (is(t,"xkb_keycodes")) { codes = true; symbols = false; continue; }
        if (is(t,"xkb_types") || is(t,"xkb_compatibility") || is(t,"xkb_geometry")) { codes = symbols = false; continue; }
        if (is(t,"xkb_symbols")) { symbols = true; codes = false; continue; }
        if (codes && t.start[0] == '<') {
            Lexer look = l;
            uint32_t c;
            if (is(next(&look),"=") && number(next(&look),10,&c)) { valid = addKey(map,t,c); l = look; }
        } else if (symbols && is(t,"key")) {
            Token name = next(&l);
            if (name.size && name.start[0] == '<' && is(next(&l),"{")) { readSymbols(&l,keyNamed(map,name)); }
        }
    }
    munmap(data,size);
    if (!valid || !map->count) { btrcWaylandKeymapFree(map); return NULL; }
    for (size_t i = 0; i < map->count; i++) { map->keys[i].name = (Token){0}; }
    return map;
}

void btrcWaylandKeymapFree(BtrcWaylandKeymap *map) { if (map) { free(map->keys); free(map); } }

static unsigned special(uint32_t sym) {
    switch(sym) {
    case 0xff1b: return BTRC_SHIM_KEY_ESCAPE;
    case 0xff0d: return BTRC_SHIM_KEY_RETURN;
    case 0xff8d: return BTRC_SHIM_KEY_KP_ENTER;
    case ' ': return BTRC_SHIM_KEY_SPACE;
    case 0xff51: return BTRC_SHIM_KEY_LEFT;
    case 0xff53: return BTRC_SHIM_KEY_RIGHT;
    case 0xff52: return BTRC_SHIM_KEY_UP;
    case 0xff54: return BTRC_SHIM_KEY_DOWN;
    case 0xff09: case 0xfe20: return BTRC_SHIM_KEY_TAB;
    case 0xff08: return BTRC_SHIM_KEY_BACKSPACE;
    case 0xffff: return BTRC_SHIM_KEY_DELETE;
    case 0xff50: return BTRC_SHIM_KEY_HOME;
    case 0xff57: return BTRC_SHIM_KEY_END;
    case 0xffe1: return BTRC_SHIM_KEY_LSHIFT;
    case 0xffe2: return BTRC_SHIM_KEY_RSHIFT;
    case 0xffe9: return BTRC_SHIM_KEY_LALT;
    case 0xffea: return BTRC_SHIM_KEY_RALT;
    case 'a': case 'A': return BTRC_SHIM_KEY_A;
    case 'c': case 'C': return BTRC_SHIM_KEY_C;
    case 'v': case 'V': return BTRC_SHIM_KEY_V;
    default: return 0;
    }
}

static void utf8(uint32_t cp, char text[5]) {
    if (cp < 0x20 || (cp > 0x7e && cp < 0xa0) || cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff)) { return; }
    if (cp < 0x80) { text[0]=(char)cp; return; }
    int size = cp < 0x800 ? 2 : cp < 0x10000 ? 3 : 4;
    for (int i = size-1; i>0; i--) { text[i]=(char)(0x80 | (cp&63)); cp >>= 6; }
    text[0]=(char)((size == 2 ? 0xc0 : size == 3 ? 0xe0 : 0xf0) | cp);
}

BtrcWaylandKey btrcWaylandKey(BtrcWaylandKeymap *map, uint32_t evdev, uint32_t mods, uint32_t group) {
    BtrcWaylandKey result = {0};
    if (!map || evdev > UINT32_MAX-8) { return result; }
    for (size_t i = 0; i < map->count; i++) {
        Key *k = &map->keys[i];
        if (k->code != evdev+8) { continue; }
        if (group >= 4 || !k->levels[group][0]) { group = 0; }
        uint32_t *levels = k->levels[group];
        bool shift = (mods & 1u) != 0;
        if ((mods & 2) && levels[0] >= 'a' && levels[0] <= 'z' && levels[1] == levels[0]-32) { shift = !shift; }
        unsigned level = (shift ? 1u : 0u) + ((mods & 128u) ? 2u : 0u);
        uint32_t sym = levels[level] ? levels[level] : levels[0];
        result.key = special(sym);
        /* Text, navigation and deletion normally repeat. Modifier keys in
         * the default XKB compatibility map do not; explicit per-key repeat
         * settings take precedence in either direction. */
        bool text = (sym >= 0x20 && sym <= 0xfeff) || (sym & 0xff000000u) == 0x01000000u;
        bool command = (sym >= 0xff08 && sym <= 0xff1b) || (sym >= 0xff50 && sym <= 0xff58) || sym == 0xffff || sym == 0xff8d;
        result.repeats = k->repeat ? k->repeat > 0 : text || command;
        result.scancode = levels[0] < 128 ? levels[0] : levels[0] == 0xff51 ? BTRC_SHIM_SCANCODE_LEFT :
            levels[0] == 0xff57 ? BTRC_SHIM_SCANCODE_END : levels[0] == 0xff08 ? BTRC_SHIM_SCANCODE_BACKSPACE : 0;
        if (!(mods & (4u|8u|64u))) {
            if (sym <= 255 || sym == 0x20ac) { utf8(sym,result.text); }
            else if ((sym & 0xff000000u) == 0x01000000u) { utf8(sym & 0xffffffu,result.text); }
        }
        break;
    }
    return result;
}
