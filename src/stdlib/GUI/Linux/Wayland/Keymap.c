#include "Keymap.h"
#include "../../Shim/Shim.h"

#include <ctype.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>

typedef struct { const char *start; size_t size; } Token;
typedef struct { const char *cursor; const char *end; } Lexer;

enum { NUM_LOCK = 1u << 8, LEVEL_THREE = 1u << 9, LEVEL_FIVE = 1u << 10 };
typedef struct { unsigned modifiers, level, preserved; } LevelMapping;
typedef struct {
    Token name;
    unsigned modifiers;
    LevelMapping *rows;
    size_t count;
    bool supported;
} KeyType;
typedef struct {
    Token name;
    uint32_t code;
    uint32_t levels[4][8];
    size_t types[4];
    unsigned levelCount[4];
    unsigned realModifiers;
    int repeat;
} Key;

struct BtrcWaylandKeymap {
    size_t count;
    size_t capacity;
    Key *keys;
    KeyType *types;
    size_t typeCount;
    unsigned numLockMask, levelThreeMask, levelFiveMask;
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
    {"EuroSign",0x20ac},{"Ooblique",0xd8},{"ooblique",0xf8},
    {"Num_Lock",0xff7f},{"ISO_Level3_Shift",0xfe03},{"ISO_Level3_Latch",0xfe04},{"ISO_Level3_Lock",0xfe05},
    {"ISO_Level5_Shift",0xfe11},{"ISO_Level5_Latch",0xfe12},{"ISO_Level5_Lock",0xfe13},
    {"KP_Space",0xff80},{"KP_Tab",0xff89},{"KP_Home",0xff95},{"KP_Left",0xff96},{"KP_Up",0xff97},
    {"KP_Right",0xff98},{"KP_Down",0xff99},{"KP_Prior",0xff9a},{"KP_Page_Up",0xff9a},
    {"KP_Next",0xff9b},{"KP_Page_Down",0xff9b},{"KP_End",0xff9c},{"KP_Begin",0xff9d},
    {"KP_Insert",0xff9e},{"KP_Delete",0xff9f},{"KP_Multiply",0xffaa},{"KP_Add",0xffab},
    {"KP_Separator",0xffac},{"KP_Subtract",0xffad},{"KP_Decimal",0xffae},{"KP_Divide",0xffaf},{"KP_Equal",0xffbd},
    {"Escape",0xff1b},{"Return",0xff0d},{"KP_Enter",0xff8d},{"Left",0xff51},{"Up",0xff52},
    {"Right",0xff53},{"Down",0xff54},{"Tab",0xff09},{"ISO_Left_Tab",0xfe20},{"BackSpace",0xff08},
    {"Delete",0xffff},{"Home",0xff50},{"End",0xff57},{"Shift_L",0xffe1},{"Shift_R",0xffe2},
    {"Alt_L",0xffe9},{"Alt_R",0xffea}
};

/* The printable Latin-1 keysyms are named in ISO 8859-1 code-point order. */
static const char *const latin1[] = {
    "nobreakspace","exclamdown","cent","sterling","currency","yen","brokenbar","section",
    "diaeresis","copyright","ordfeminine","guillemotleft","notsign","hyphen","registered","macron",
    "degree","plusminus","twosuperior","threesuperior","acute","mu","paragraph","periodcentered",
    "cedilla","onesuperior","masculine","guillemotright","onequarter","onehalf","threequarters","questiondown",
    "Agrave","Aacute","Acircumflex","Atilde","Adiaeresis","Aring","AE","Ccedilla",
    "Egrave","Eacute","Ecircumflex","Ediaeresis","Igrave","Iacute","Icircumflex","Idiaeresis",
    "ETH","Ntilde","Ograve","Oacute","Ocircumflex","Otilde","Odiaeresis","multiply",
    "Oslash","Ugrave","Uacute","Ucircumflex","Udiaeresis","Yacute","THORN","ssharp",
    "agrave","aacute","acircumflex","atilde","adiaeresis","aring","ae","ccedilla",
    "egrave","eacute","ecircumflex","ediaeresis","igrave","iacute","icircumflex","idiaeresis",
    "eth","ntilde","ograve","oacute","ocircumflex","otilde","odiaeresis","division",
    "oslash","ugrave","uacute","ucircumflex","udiaeresis","yacute","thorn","ydiaeresis"
};

static uint32_t symbol(Token t) {
    if (t.size == 4 && !memcmp(t.start, "KP_", 3) && t.start[3] >= '0' && t.start[3] <= '9') {
        return 0xffb0u + (unsigned)(t.start[3] - '0');
    }
    if (t.size == 1 && (unsigned char)t.start[0] < 128) { return (unsigned char)t.start[0]; }
    uint32_t value;
    if (t.size >= 3 && t.start[0] == '0' && t.start[1] == 'x' && number((Token){t.start+2,t.size-2},16,&value)) { return value; }
    if (t.size >= 5 && t.start[0] == 'U' && number((Token){t.start+1,t.size-1},16,&value) && value <= 0x10ffff) {
        return value < 256 ? value : 0x01000000u | value;
    }
    for (size_t i = 0; i < sizeof(latin1)/sizeof(*latin1); ++i) { if (is(t, latin1[i])) { return 0xa0u + (unsigned)i; } }
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

/* Core modifiers use fixed XKB wire positions. The compositor binds the
 * virtual level selectors to core modifiers in its compiled keymap. */
static unsigned modifier(Token name) {
    if (is(name, "Shift")) { return 1u; }
    if (is(name, "Lock")) { return 2u; }
    if (is(name, "Control")) { return 4u; }
    if (name.size == 4 && !memcmp(name.start, "Mod", 3) && name.start[3] >= '1' && name.start[3] <= '5') {
        return 1u << (name.start[3] - '1' + 3);
    }
    if (is(name, "NumLock")) { return NUM_LOCK; }
    if (is(name, "LevelThree")) { return LEVEL_THREE; }
    if (is(name, "LevelFive")) { return LEVEL_FIVE; }
    return 0;
}

static bool readMask(Lexer *l, const char *end, unsigned *mask) {
    bool supported = true;
    *mask = 0;
    for (Token t = next(l); t.size; t = next(l)) {
        if (is(t, end)) { return supported; }
        if (is(t, "+") || is(t, "None") || is(t, "none")) { continue; }
        unsigned bit = modifier(t);
        supported &= bit != 0;
        *mask |= bit;
    }
    return false;
}

static size_t typeIndex(const BtrcWaylandKeymap *map, Token name) {
    for (size_t i = 0; i < map->typeCount; ++i) {
        Token key = map->types[i].name;
        if (key.size == name.size && !memcmp(key.start, name.start, name.size)) { return i + 1; }
    }
    return 0;
}

static LevelMapping *typeRow(KeyType *type, unsigned mask) {
    for (size_t i = 0; i < type->count; ++i) {
        if (type->rows[i].modifiers == mask) { return &type->rows[i]; }
    }
    if (type->count >= SIZE_MAX / sizeof(*type->rows)) { return NULL; }
    LevelMapping *rows = realloc(type->rows, (type->count + 1) * sizeof(*rows));
    if (!rows) { return NULL; }
    type->rows = rows;
    rows[type->count] = (LevelMapping){.modifiers = mask};
    return &rows[type->count++];
}

static bool readType(BtrcWaylandKeymap *map, Lexer *l) {
    Token name = next(l);
    if (name.size < 2 || name.start[0] != '"' || !is(next(l), "{")) { return true; }
    if (map->typeCount >= SIZE_MAX / sizeof(*map->types)) { return false; }
    KeyType *types = realloc(map->types, (map->typeCount + 1) * sizeof(*types));
    if (!types) { return false; }
    map->types = types;
    KeyType *type = &types[map->typeCount++];
    *type = (KeyType){.name = name, .supported = true};
    for (;;) {
        Token t = next(l);
        if (!t.size) { return false; }
        if (is(t, "}")) { return true; }
        if (is(t, "modifiers") && is(next(l), "=")) {
            type->supported &= readMask(l, ";", &type->modifiers);
        } else if ((is(t, "map") || is(t, "preserve")) && is(next(l), "[")) {
            unsigned mask;
            bool known = readMask(l, "]", &mask);
            if (!is(next(l), "=")) { return false; }
            LevelMapping *row = known ? typeRow(type, mask) : NULL;
            if (known && !row) { return false; }
            if (is(t, "preserve")) {
                unsigned preserved;
                bool understood = readMask(l, ";", &preserved);
                if (row && understood) { row->preserved = preserved; }
            } else {
                Token levelName = next(l);
                if (levelName.size > 5 && !memcmp(levelName.start, "Level", 5)) {
                    levelName.start += 5;
                    levelName.size -= 5;
                }
                uint32_t level;
                if (row && number(levelName, 10, &level) && level >= 1 && level <= 8) { row->level = level - 1; }
            }
        }
    }
}

static unsigned selectedGroup(Token token) {
    return token.size == 6 && !memcmp(token.start, "Group", 5) && token.start[5] >= '1' && token.start[5] <= '4'
        ? (unsigned)(token.start[5] - '1') : 4;
}

static void readModifierMap(BtrcWaylandKeymap *map, Lexer *l) {
    unsigned wireMask = modifier(next(l));
    if (!is(next(l), "{")) { return; }
    for (Token t = next(l); t.size && !is(t, "}"); t = next(l)) {
        if (t.start[0] != '<') { continue; }
        Key *key = keyNamed(map, t);
        if (key) { key->realModifiers |= wireMask; }
    }
}

static void readSymbols(BtrcWaylandKeymap *map, Lexer *l, Key *key) {
    unsigned group = 0;
    unsigned depth = 1;
    while (depth) {
        Token t = next(l);
        if (!t.size) { return; }
        if (is(t,"{")) { depth++; continue; }
        if (is(t,"}")) { depth--; continue; }
        if (depth != 1) { continue; }
        if (is(t,"type")) {
            unsigned target = 0;
            Token equals = next(l);
            if (is(equals, "[")) {
                target = selectedGroup(next(l));
                if (!is(next(l), "]")) { continue; }
                equals = next(l);
            }
            if (is(equals, "=")) {
                Token type = next(l);
                if (key && target < 4) { key->types[target] = typeIndex(map, type); }
            }
            continue;
        }
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
        if (selectedGroup(first) < 4) {
            /* A group selector in type[GroupN] or symbols[GroupN]. */
            group = selectedGroup(first);
            while ((t = next(l)).size && !is(t,"]")) { }
            continue;
        }
        unsigned level = 0;
        while ((t = next(l)).size && !is(t,"]")) {
            if (is(t,",")) { continue; }
            if (key && group < 4 && level < 8) {
                key->levels[group][level] = symbol(t);
                key->levelCount[group] = level + 1;
            }
            ++level;
        }
        ++group;
    }
}

static uint32_t upperLatin(uint32_t lower) {
    bool latin = (lower >= 'a' && lower <= 'z') || (lower >= 0xe0 && lower <= 0xf6) || (lower >= 0xf8 && lower <= 0xfe);
    return latin ? lower - 32 : lower;
}

static bool alphabeticPair(uint32_t lower, uint32_t upper) {
    return lower != upper && upperLatin(lower) == upper;
}

/* XKB supplies the type by name for unusual bindings. A shorthand symbol
 * array takes its standard type from its width, case pairs and keypad symbols. */
static const char *implicitType(unsigned count, const uint32_t *levels) {
    if (count < 2) { return "\"ONE_LEVEL\""; }
    bool keypad = (levels[0] >= 0xff80 && levels[0] <= 0xffbd) || (levels[1] >= 0xff80 && levels[1] <= 0xffbd);
    bool alphabetic = alphabeticPair(levels[0], levels[1]);
    if (count == 2) { return keypad ? "\"KEYPAD\"" : alphabetic ? "\"ALPHABETIC\"" : "\"TWO_LEVEL\""; }
    if (count > 4) { return NULL; }
    if (keypad) { return "\"FOUR_LEVEL_KEYPAD\""; }
    if (!alphabetic) { return "\"FOUR_LEVEL\""; }
    return alphabeticPair(levels[2], levels[3]) ? "\"FOUR_LEVEL_ALPHABETIC\"" : "\"FOUR_LEVEL_SEMIALPHABETIC\"";
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
    bool types = false;
    Token t;
    while (valid && (t = next(&l)).size) {
        if (is(t,"xkb_keycodes")) { codes = true; symbols = types = false; continue; }
        if (is(t,"xkb_types")) { types = true; codes = symbols = false; continue; }
        if (is(t,"xkb_compatibility") || is(t,"xkb_geometry")) { codes = symbols = types = false; continue; }
        if (is(t,"xkb_symbols")) { symbols = true; codes = types = false; continue; }
        if (codes && t.start[0] == '<') {
            Lexer look = l;
            uint32_t c;
            if (is(next(&look),"=") && number(next(&look),10,&c)) { valid = addKey(map,t,c); l = look; }
        } else if (types && is(t, "type")) {
            valid = readType(map, &l);
        } else if (symbols && is(t, "modifier_map")) {
            readModifierMap(map, &l);
        } else if (symbols && is(t,"key")) {
            Token name = next(&l);
            if (name.size && name.start[0] == '<' && is(next(&l),"{")) { readSymbols(map,&l,keyNamed(map,name)); }
        }
    }
    if (valid) {
        for (size_t i = 0; i < map->count; ++i) {
            Key *key = &map->keys[i];
            for (unsigned g = 0; g < 4; ++g) {
                uint32_t *levels = key->levels[g];
                if (!key->types[g] && key->levelCount[g]) {
                    const char *type = implicitType(key->levelCount[g], levels);
                    if (type) { key->types[g] = typeIndex(map, (Token){type, strlen(type)}); }
                }
                for (unsigned j = 0; j < 8; ++j) {
                    uint32_t sym = levels[j];
                    if (sym == 0xff7f) { map->numLockMask |= key->realModifiers; }
                    if (sym >= 0xfe03 && sym <= 0xfe05) { map->levelThreeMask |= key->realModifiers; }
                    if (sym >= 0xfe11 && sym <= 0xfe13) { map->levelFiveMask |= key->realModifiers; }
                }
            }
        }
    }
    if (map) { for (size_t i = 0; i < map->typeCount; ++i) { map->types[i].name = (Token){0}; } }
    munmap(data,size);
    if (!valid || !map->count) { btrcWaylandKeymapFree(map); return NULL; }
    for (size_t i = 0; i < map->count; i++) { map->keys[i].name = (Token){0}; }
    return map;
}

void btrcWaylandKeymapFree(BtrcWaylandKeymap *map) {
    if (!map) { return; }
    for (size_t i = 0; i < map->typeCount; ++i) { free(map->types[i].rows); }
    free(map->types);
    free(map->keys);
    free(map);
}

static unsigned special(uint32_t sym) {
    switch(sym) {
    case 0xff1b: return BTRC_SHIM_KEY_ESCAPE;
    case 0xff0d: return BTRC_SHIM_KEY_RETURN;
    case 0xff8d: return BTRC_SHIM_KEY_KP_ENTER;
    case 0xff80: case ' ': return BTRC_SHIM_KEY_SPACE;
    case 0xff51: case 0xff96: return BTRC_SHIM_KEY_LEFT;
    case 0xff53: case 0xff98: return BTRC_SHIM_KEY_RIGHT;
    case 0xff52: case 0xff97: return BTRC_SHIM_KEY_UP;
    case 0xff54: case 0xff99: return BTRC_SHIM_KEY_DOWN;
    case 0xff09: case 0xff89: case 0xfe20: return BTRC_SHIM_KEY_TAB;
    case 0xff08: return BTRC_SHIM_KEY_BACKSPACE;
    case 0xffff: case 0xff9f: return BTRC_SHIM_KEY_DELETE;
    case 0xff50: case 0xff95: return BTRC_SHIM_KEY_HOME;
    case 0xff57: case 0xff9c: return BTRC_SHIM_KEY_END;
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

static uint32_t symbolForModifiers(const BtrcWaylandKeymap *map, const Key *key, unsigned group, unsigned mods) {
    const uint32_t *levels = key->levels[group];
    const KeyType *type = key->types[group] ? &map->types[key->types[group] - 1] : NULL;
    if (!type || !type->supported) {
        bool shift = (mods & 1u) != 0;
        if ((mods & 2u) && alphabeticPair(levels[0], levels[1])) { shift = !shift; }
        unsigned level = (shift ? 1u : 0u) + ((mods & 128u) ? 2u : 0u);
        return levels[level] ? levels[level] : levels[0];
    }
    unsigned active = mods & 255u;
    if (mods & map->numLockMask) { active |= NUM_LOCK; }
    if (mods & map->levelThreeMask) { active |= LEVEL_THREE; }
    if (mods & map->levelFiveMask) { active |= LEVEL_FIVE; }
    active &= type->modifiers;
    unsigned level = 0, consumed = type->modifiers;
    for (size_t i = 0; i < type->count; ++i) {
        const LevelMapping *row = &type->rows[i];
        if (row->modifiers != active) { continue; }
        level = row->level;
        consumed &= ~row->preserved;
        break;
    }
    uint32_t sym = levels[level];
    return (mods & 2u) && !(consumed & 2u) ? upperLatin(sym) : sym;
}

BtrcWaylandKey btrcWaylandKey(BtrcWaylandKeymap *map, uint32_t evdev, uint32_t mods, uint32_t group) {
    BtrcWaylandKey result = {0};
    if (!map || evdev > UINT32_MAX-8) { return result; }
    for (size_t i = 0; i < map->count; i++) {
        Key *k = &map->keys[i];
        if (k->code != evdev+8) { continue; }
        if (group >= 4 || !k->levelCount[group]) { group = 0; }
        uint32_t *levels = k->levels[group];
        uint32_t sym = symbolForModifiers(map, k, group, mods);
        result.key = special(sym);
        /* Text, navigation and deletion normally repeat. Modifier keys in
         * the default XKB compatibility map do not; explicit per-key repeat
         * settings take precedence in either direction. */
        bool text = (sym >= 0x20 && sym <= 0xfeff) || (sym & 0xff000000u) == 0x01000000u;
        bool command = (sym >= 0xff95 && sym <= 0xffbd) || (sym >= 0xff08 && sym <= 0xff1b) || (sym >= 0xff50 && sym <= 0xff58) || sym == 0xffff || sym == 0xff8d;
        result.repeats = k->repeat ? k->repeat > 0 : text || command;
        result.scancode = levels[0] < 128 ? levels[0] : levels[0] == 0xff51 ? BTRC_SHIM_SCANCODE_LEFT :
            levels[0] == 0xff57 ? BTRC_SHIM_SCANCODE_END : levels[0] == 0xff08 ? BTRC_SHIM_SCANCODE_BACKSPACE : 0;
        if (!(mods & (4u|8u|64u))) {
            if (sym == 0xff80) { sym = ' '; }
            if (sym == 0xffbd) { sym = '='; }
            if (sym >= 0xffaa && sym <= 0xffb9) { sym = '*' + (sym - 0xffaa); }
            if (sym <= 255 || sym == 0x20ac) { utf8(sym,result.text); }
            else if ((sym & 0xff000000u) == 0x01000000u) { utf8(sym & 0xffffffu,result.text); }
        }
        break;
    }
    return result;
}
