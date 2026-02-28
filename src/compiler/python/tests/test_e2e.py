"""End-to-end tests for the btrc transpiler.

Each test: btrc source → lexer → parser → analyzer → IR gen → optimize → emit → gcc → run → check output.
"""

import subprocess
import tempfile
import os

import pytest
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.ir.gen.generator import IRGenerator
from src.compiler.python.ir.optimizer import optimize as optimize_module
from src.compiler.python.ir.emitter import CEmitter
from src.compiler.python.main import get_stdlib_source


def compile_and_run(btrc_source: str, extra_flags: list[str] = None) -> str:
    """Transpile btrc source to C, compile with gcc, run, return stdout."""
    # Auto-include stdlib types (skip classes already defined in source)
    stdlib_source = get_stdlib_source(btrc_source)
    if stdlib_source:
        btrc_source = stdlib_source + "\n" + btrc_source
    tokens = Lexer(btrc_source).tokenize()
    program = Parser(tokens).parse()
    analyzed = Analyzer().analyze(program)
    assert not analyzed.errors, f"Analyzer errors: {analyzed.errors}"
    ir_module = IRGenerator(analyzed).generate()
    optimized = optimize_module(ir_module)
    c_source = CEmitter().emit(optimized)

    with tempfile.NamedTemporaryFile(suffix=".c", mode="w", delete=False) as f:
        f.write(c_source)
        c_path = f.name

    bin_path = c_path.replace(".c", "")

    try:
        flags = ["gcc", c_path, "-o", bin_path, "-lm"]
        if extra_flags:
            flags.extend(extra_flags)
        result = subprocess.run(flags, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            pytest.fail(f"Compilation failed:\n{result.stderr}\n\nGenerated C:\n{c_source}")

        result = subprocess.run([bin_path], capture_output=True, text=True, timeout=10)
        return result.stdout
    finally:
        for p in [c_path, bin_path]:
            if os.path.exists(p):
                os.unlink(p)


def compile_and_check_errors(btrc_source: str) -> list[str]:
    """Transpile btrc source and return analyzer errors (don't compile)."""
    tokens = Lexer(btrc_source).tokenize()
    program = Parser(tokens).parse()
    analyzed = Analyzer().analyze(program)
    return analyzed.errors


# --- E2E Tests ---

class TestE2EHelloWorld:
    def test_hello(self):
        src = '''
            #include <stdio.h>
            int main() {
                printf("hello\\n");
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "hello"


class TestE2EPureC:
    def test_variables_and_math(self):
        src = '''
            #include <stdio.h>
            int main() {
                int a = 10;
                int b = 20;
                int c = a + b;
                printf("%d\\n", c);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "30"

    def test_c_for_loop(self):
        src = '''
            #include <stdio.h>
            int main() {
                int sum = 0;
                for (int i = 1; i <= 5; i++) {
                    sum += i;
                }
                printf("%d\\n", sum);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "15"

    def test_if_else(self):
        src = '''
            #include <stdio.h>
            int main() {
                int x = 42;
                if (x > 10) {
                    printf("big\\n");
                } else {
                    printf("small\\n");
                }
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "big"

    def test_while_loop(self):
        src = '''
            #include <stdio.h>
            int main() {
                int i = 0;
                int sum = 0;
                while (i < 5) {
                    sum += i;
                    i++;
                }
                printf("%d\\n", sum);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "10"

    def test_function_call(self):
        src = '''
            #include <stdio.h>
            int square(int x) { return x * x; }
            int main() {
                printf("%d\\n", square(7));
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "49"

    def test_ternary(self):
        src = '''
            #include <stdio.h>
            int main() {
                int x = 5;
                int y = x > 3 ? 100 : 0;
                printf("%d\\n", y);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "100"


class TestE2EClasses:
    def test_class_basic(self):
        src = '''
            #include <stdio.h>
            class Counter {
                private int count;
                public Counter() { self.count = 0; }
                public void inc() { self.count++; }
                public int get() { return self.count; }
            }
            int main() {
                Counter c = Counter();
                c.inc();
                c.inc();
                c.inc();
                printf("%d\\n", c.get());
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "3"

    def test_static_method(self):
        src = '''
            #include <stdio.h>
            class Math {
                class int square(int x) { return x * x; }
            }
            int main() {
                printf("%d\\n", Math.square(5));
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "25"

    def test_constructor_with_params(self):
        src = '''
            #include <stdio.h>
            class Point {
                public int x;
                public int y;
                public Point(int x, int y) {
                    self.x = x;
                    self.y = y;
                }
            }
            int main() {
                Point p = Point(10, 20);
                printf("%d %d\\n", p.x, p.y);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "10 20"


class TestE2ENewDelete:
    def test_new_delete(self):
        src = '''
            #include <stdio.h>
            class Node {
                public int val;
                public Node(int v) { self.val = v; }
            }
            int main() {
                Node n = new Node(99);
                printf("%d\\n", n.val);
                delete n;
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "99"


class TestE2EList:
    def test_list_basic(self):
        src = '''
            #include <stdio.h>
            int main() {
                Vector<int> nums = [10, 20, 30];
                int sum = 0;
                for x in nums {
                    sum += x;
                }
                printf("%d\\n", sum);
                nums.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "60"

    def test_list_push(self):
        src = '''
            #include <stdio.h>
            int main() {
                Vector<int> nums = [];
                nums.push(1);
                nums.push(2);
                nums.push(3);
                printf("%d\\n", nums.len);
                nums.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "3"


class TestE2EBoolString:
    def test_bool(self):
        src = '''
            #include <stdio.h>
            int main() {
                bool a = true;
                bool b = false;
                printf("%d %d\\n", a, b);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "1 0"

    def test_string(self):
        src = '''
            #include <stdio.h>
            int main() {
                string s = "world";
                printf("hello %s\\n", s);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "hello world"


class TestE2EDotSyntax:
    def test_class_dot_method(self):
        src = '''
            #include <stdio.h>
            class Adder {
                private int total;
                public Adder() { self.total = 0; }
                public void add(int n) { self.total += n; }
                public int result() { return self.total; }
            }
            int main() {
                Adder a = Adder();
                a.add(10);
                a.add(20);
                a.add(30);
                printf("%d\\n", a.result());
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "60"

    def test_class_arrow_method(self):
        src = '''
            #include <stdio.h>
            class Box {
                public int val;
                public Box(int v) { self.val = v; }
                public int get() { return self.val; }
            }
            int main() {
                Box b = new Box(42);
                printf("%d\\n", b.get());
                delete b;
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "42"

    def test_list_dot_methods(self):
        src = '''
            #include <stdio.h>
            int main() {
                Vector<int> nums = [];
                nums.push(100);
                nums.push(200);
                nums.push(300);
                int sum = 0;
                for x in nums {
                    sum += x;
                }
                printf("%d %d\\n", nums.len, sum);
                nums.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "3 600"

    def test_map_dot_methods(self):
        src = '''
            #include <stdio.h>
            int main() {
                Map<string, int> ages = {"alice": 30, "bob": 25};
                printf("%d\\n", ages.get("alice"));
                ages.put("carol", 35);
                printf("%d\\n", ages.get("carol"));
                ages.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "30\n35"


class TestE2ECollectionIndexing:
    def test_list_index_read(self):
        src = '''
            #include <stdio.h>
            int main() {
                Vector<int> nums = [10, 20, 30];
                printf("%d %d %d\\n", nums[0], nums[1], nums[2]);
                nums.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "10 20 30"

    def test_list_index_write(self):
        src = '''
            #include <stdio.h>
            int main() {
                Vector<int> nums = [1, 2, 3];
                nums[1] = 99;
                printf("%d\\n", nums[1]);
                nums.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "99"


class TestE2EDefaultConstructor:
    def test_default_field_values(self):
        src = '''
            #include <stdio.h>
            class Config {
                public int width = 800;
                public int height = 600;
                public int fps = 60;
            }
            int main() {
                Config c = Config();
                printf("%d %d %d\\n", c.width, c.height, c.fps);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "800 600 60"

    def test_explicit_constructor_with_defaults(self):
        src = '''
            #include <stdio.h>
            class Rect {
                public int x = 0;
                public int y = 0;
                public int w;
                public int h;
                public Rect(int w, int h) {
                    self.w = w;
                    self.h = h;
                }
            }
            int main() {
                Rect r = Rect(100, 50);
                printf("%d %d %d %d\\n", r.x, r.y, r.w, r.h);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "0 0 100 50"


class TestE2EOperatorOverload:
    def test_vec2_add(self):
        src = '''
            #include <stdio.h>
            class Vec2 {
                public int x;
                public int y;
                public Vec2(int x, int y) {
                    self.x = x;
                    self.y = y;
                }
                public Vec2 __add__(Vec2 other) {
                    return Vec2(self.x + other.x, self.y + other.y);
                }
                public bool __eq__(Vec2 other) {
                    return self.x == other.x && self.y == other.y;
                }
            }
            int main() {
                Vec2 a = Vec2(1, 2);
                Vec2 b = Vec2(3, 4);
                Vec2 c = a + b;
                printf("%d %d\\n", c.x, c.y);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "4 6"


class TestE2EPrint:
    def test_print_hello(self):
        src = '''
            int main() {
                print("hello");
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "hello"

    def test_print_int(self):
        src = '''
            int main() {
                int x = 42;
                print(x);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "42"

    def test_print_multi_args(self):
        src = '''
            int main() {
                int a = 1;
                int b = 2;
                print(a, b);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "1 2"

    def test_print_empty(self):
        src = '''
            int main() {
                print();
                print("done");
                return 0;
            }
        '''
        output = compile_and_run(src)
        assert output == "\ndone\n"


class TestE2EFString:
    def test_fstring_basic(self):
        src = '''
            int main() {
                int x = 42;
                print(f"x={x}");
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "x=42"

    def test_fstring_multi_expr(self):
        src = '''
            int main() {
                int a = 3;
                int b = 4;
                int c = a + b;
                print(f"{a} + {b} = {c}");
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "3 + 4 = 7"

    def test_fstring_with_string(self):
        src = '''
            int main() {
                string name = "world";
                print(f"hello {name}");
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "hello world"


    def test_fstring_as_variable(self):
        src = '''
            #include <stdio.h>
            int main() {
                int age = 25;
                string msg = f"Age is {age}";
                printf("%s\\n", msg);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "Age is 25"

    def test_fstring_return_from_function(self):
        src = '''
            #include <stdio.h>
            string format_pair(int a, int b) {
                return f"{a} and {b}";
            }
            int main() {
                printf("%s\\n", format_pair(3, 7));
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "3 and 7"

    def test_fstring_reassignment(self):
        src = '''
            #include <stdio.h>
            int main() {
                string s = "initial";
                int x = 42;
                s = f"updated: {x}";
                printf("%s\\n", s);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "updated: 42"


class TestE2EAutoInclude:
    def test_auto_include_math(self):
        src = '''
            int main() {
                double x = sqrt(4.0);
                printf("%g\\n", x);
                return 0;
            }
        '''
        assert compile_and_run(src, extra_flags=["-lm"]).strip() == "2"

    def test_user_include_preserved(self):
        src = '''
            #include <stdio.h>
            #include <math.h>
            int main() {
                double x = sqrt(9.0);
                printf("%g\\n", x);
                return 0;
            }
        '''
        assert compile_and_run(src, extra_flags=["-lm"]).strip() == "3"


class TestE2EMapAutoResize:
    def test_map_many_insertions(self):
        """Insert 100 entries into a map (initial cap 16), verify all retrievable."""
        src = '''
            #include <stdio.h>
            int main() {
                Map<int, int> m = {0: 0};
                for (int i = 1; i < 100; i++) {
                    m.put(i, i * i);
                }
                int ok = 1;
                for (int i = 0; i < 100; i++) {
                    if (m.get(i) != i * i) {
                        ok = 0;
                    }
                }
                printf("%d %d\\n", m.len, ok);
                m.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "100 1"


class TestE2EComplexC:
    def test_linked_list(self):
        """Singly linked list with insert, traverse, and free."""
        src = '''
            #include <stdio.h>
            #include <stdlib.h>
            struct Node {
                int val;
                struct Node* next;
            };
            struct Node* insert(struct Node* head, int val) {
                struct Node* n = (struct Node*)malloc(sizeof(struct Node));
                n->val = val;
                n->next = head;
                return n;
            }
            void print_list(struct Node* head) {
                struct Node* cur = head;
                while (cur != NULL) {
                    printf("%d ", cur->val);
                    cur = cur->next;
                }
                printf("\\n");
            }
            void free_list(struct Node* head) {
                while (head != NULL) {
                    struct Node* tmp = head;
                    head = head->next;
                    free(tmp);
                }
            }
            int main() {
                struct Node* list = NULL;
                for (int i = 1; i <= 5; i++) {
                    list = insert(list, i);
                }
                print_list(list);
                free_list(list);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "5 4 3 2 1"

    def test_recursive_tree(self):
        """Binary search tree with recursive insert and inorder traversal."""
        src = '''
            #include <stdio.h>
            #include <stdlib.h>
            struct TreeNode {
                int val;
                struct TreeNode* left;
                struct TreeNode* right;
            };
            struct TreeNode* new_node(int val) {
                struct TreeNode* n = (struct TreeNode*)malloc(sizeof(struct TreeNode));
                n->val = val;
                n->left = NULL;
                n->right = NULL;
                return n;
            }
            struct TreeNode* bst_insert(struct TreeNode* root, int val) {
                if (root == NULL) { return new_node(val); }
                if (val < root->val) { root->left = bst_insert(root->left, val); }
                else { root->right = bst_insert(root->right, val); }
                return root;
            }
            void inorder(struct TreeNode* root) {
                if (root == NULL) { return; }
                inorder(root->left);
                printf("%d ", root->val);
                inorder(root->right);
            }
            void free_tree(struct TreeNode* root) {
                if (root == NULL) { return; }
                free_tree(root->left);
                free_tree(root->right);
                free(root);
            }
            int main() {
                struct TreeNode* root = NULL;
                root = bst_insert(root, 5);
                root = bst_insert(root, 3);
                root = bst_insert(root, 7);
                root = bst_insert(root, 1);
                root = bst_insert(root, 4);
                root = bst_insert(root, 6);
                root = bst_insert(root, 8);
                root = bst_insert(root, 2);
                inorder(root);
                printf("\\n");
                free_tree(root);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "1 2 3 4 5 6 7 8"

    def test_string_operations(self):
        """String manipulation using string.h functions."""
        src = '''
            #include <stdio.h>
            #include <string.h>
            #include <stdlib.h>
            int main() {
                char buf[128];
                strcpy(buf, "hello");
                strcat(buf, " ");
                strcat(buf, "world");
                printf("%d\\n", (int)strlen(buf));
                printf("%d\\n", strcmp(buf, "hello world") == 0 ? 1 : 0);
                char* found = strstr(buf, "world");
                printf("%s\\n", found);
                return 0;
            }
        '''
        output = compile_and_run(src).strip()
        assert output == "11\n1\nworld"

    def test_sorting_quicksort(self):
        """Quicksort implementation on an integer array."""
        src = '''
            #include <stdio.h>
            void swap(int* a, int* b) {
                int tmp = *a;
                *a = *b;
                *b = tmp;
            }
            int partition(int arr[], int low, int high) {
                int pivot = arr[high];
                int i = low - 1;
                for (int j = low; j < high; j++) {
                    if (arr[j] <= pivot) {
                        i++;
                        swap(&arr[i], &arr[j]);
                    }
                }
                swap(&arr[i + 1], &arr[high]);
                return i + 1;
            }
            void quicksort(int arr[], int low, int high) {
                if (low < high) {
                    int pi = partition(arr, low, high);
                    quicksort(arr, low, pi - 1);
                    quicksort(arr, pi + 1, high);
                }
            }
            int main() {
                int arr[] = {9, 3, 7, 1, 8, 2, 6, 4, 5, 0};
                int n = 10;
                quicksort(arr, 0, n - 1);
                for (int i = 0; i < n; i++) {
                    printf("%d ", arr[i]);
                }
                printf("\\n");
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "0 1 2 3 4 5 6 7 8 9"

    def test_struct_composition(self):
        """Nested structs, arrays of structs, and pointer-to-struct."""
        src = '''
            #include <stdio.h>
            struct Vec2 { float x; float y; };
            struct Rect {
                struct Vec2 origin;
                struct Vec2 size;
            };
            float area(struct Rect* r) {
                return r->size.x * r->size.y;
            }
            int main() {
                struct Rect rects[3];
                for (int i = 0; i < 3; i++) {
                    rects[i].origin.x = 0.0f;
                    rects[i].origin.y = 0.0f;
                    rects[i].size.x = (float)(i + 1) * 10.0f;
                    rects[i].size.y = (float)(i + 1) * 5.0f;
                }
                float total = 0.0f;
                for (int i = 0; i < 3; i++) {
                    total += area(&rects[i]);
                }
                printf("%.0f\\n", total);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "700"

    def test_hash_table(self):
        """Simple open-addressing hash table with string keys."""
        src = '''
            #include <stdio.h>
            #include <stdlib.h>
            #include <string.h>
            #define HT_CAP 64
            struct HT_Entry { char* key; int value; int used; };
            struct HashTable { struct HT_Entry entries[HT_CAP]; };
            unsigned int ht_hash(const char* key) {
                unsigned int h = 0;
                while (*key) { h = h * 31 + (unsigned char)*key++; }
                return h % HT_CAP;
            }
            void ht_set(struct HashTable* ht, const char* key, int value) {
                unsigned int idx = ht_hash(key);
                for (int i = 0; i < HT_CAP; i++) {
                    unsigned int pos = (idx + i) % HT_CAP;
                    if (!ht->entries[pos].used || strcmp(ht->entries[pos].key, key) == 0) {
                        if (!ht->entries[pos].used) {
                            ht->entries[pos].key = strdup(key);
                        }
                        ht->entries[pos].value = value;
                        ht->entries[pos].used = 1;
                        return;
                    }
                }
            }
            int ht_get(struct HashTable* ht, const char* key) {
                unsigned int idx = ht_hash(key);
                for (int i = 0; i < HT_CAP; i++) {
                    unsigned int pos = (idx + i) % HT_CAP;
                    if (!ht->entries[pos].used) { return -1; }
                    if (strcmp(ht->entries[pos].key, key) == 0) {
                        return ht->entries[pos].value;
                    }
                }
                return -1;
            }
            void ht_free(struct HashTable* ht) {
                for (int i = 0; i < HT_CAP; i++) {
                    if (ht->entries[i].used) { free(ht->entries[i].key); }
                }
            }
            int main() {
                struct HashTable ht;
                memset(&ht, 0, sizeof(struct HashTable));
                ht_set(&ht, "alpha", 1);
                ht_set(&ht, "beta", 2);
                ht_set(&ht, "gamma", 3);
                ht_set(&ht, "delta", 4);
                printf("%d %d %d %d\\n",
                    ht_get(&ht, "alpha"), ht_get(&ht, "beta"),
                    ht_get(&ht, "gamma"), ht_get(&ht, "delta"));
                ht_set(&ht, "beta", 20);
                printf("%d\\n", ht_get(&ht, "beta"));
                printf("%d\\n", ht_get(&ht, "missing"));
                ht_free(&ht);
                return 0;
            }
        '''
        output = compile_and_run(src).strip()
        assert output == "1 2 3 4\n20\n-1"


class TestE2ERange:
    def test_range_single_arg(self):
        src = '''
            int main() {
                int sum = 0;
                for i in range(5) {
                    sum += i;
                }
                print(sum);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "10"

    def test_range_two_args(self):
        src = '''
            int main() {
                int sum = 0;
                for i in range(3, 8) {
                    sum += i;
                }
                print(sum);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "25"

    def test_range_three_args(self):
        src = '''
            int main() {
                for i in range(0, 10, 3) {
                    print(i);
                }
                return 0;
            }
        '''
        output = compile_and_run(src).strip()
        assert output == "0\n3\n6\n9"

    def test_range_in_fstring(self):
        src = '''
            int main() {
                for i in range(3) {
                    print(f"val={i}");
                }
                return 0;
            }
        '''
        output = compile_and_run(src).strip()
        assert output == "val=0\nval=1\nval=2"


class TestE2ETuples:
    def test_tuple_return(self):
        src = '''
            (int, int) divmod(int a, int b) {
                return (a / b, a % b);
            }
            int main() {
                (int, int) result = divmod(17, 5);
                print(result._0);
                print(result._1);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "3\n2"

    def test_tuple_access(self):
        src = '''
            (int, int) swap(int a, int b) {
                return (b, a);
            }
            int main() {
                (int, int) t = swap(10, 20);
                print(t._0, t._1);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "20 10"

    def test_tuple_three_elements(self):
        src = '''
            (int, float, int) make_triple(int x) {
                return (x, (float)x * 1.5f, x * 2);
            }
            int main() {
                (int, float, int) t = make_triple(4);
                printf("%d %.1f %d\\n", t._0, t._1, t._2);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "4 6.0 8"


class TestE2EListMethods:
    def test_list_sort(self):
        src = '''
            #include <stdio.h>
            int main() {
                Vector<int> nums = [5, 2, 8, 1, 9, 3];
                nums.sort();
                for x in nums {
                    printf("%d ", x);
                }
                printf("\\n");
                nums.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "1 2 3 5 8 9"

    def test_list_reverse(self):
        src = '''
            #include <stdio.h>
            int main() {
                Vector<int> nums = [1, 2, 3, 4, 5];
                nums.reverse();
                for x in nums {
                    printf("%d ", x);
                }
                printf("\\n");
                nums.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "5 4 3 2 1"

    def test_list_contains(self):
        src = '''
            int main() {
                Vector<int> nums = [10, 20, 30];
                print(nums.contains(20));
                print(nums.contains(99));
                nums.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "true\nfalse"

    def test_list_remove(self):
        src = '''
            #include <stdio.h>
            int main() {
                Vector<int> nums = [10, 20, 30, 40];
                nums.remove(1);
                for x in nums {
                    printf("%d ", x);
                }
                printf("\\n");
                nums.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "10 30 40"

    def test_list_clear(self):
        src = '''
            int main() {
                Vector<int> nums = [1, 2, 3];
                nums.clear();
                print(nums.len);
                nums.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "0"


class TestE2EStringMethods:
    def test_string_len(self):
        src = '''
            int main() {
                string s = "hello";
                print(s.len());
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "5"

    def test_string_contains(self):
        src = '''
            int main() {
                string s = "hello world";
                if (s.contains("world")) {
                    print("yes");
                } else {
                    print("no");
                }
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "yes"

    def test_string_startsWith_endsWith(self):
        src = '''
            int main() {
                string s = "hello world";
                print(s.startsWith("hello"));
                print(s.endsWith("world"));
                print(s.startsWith("world"));
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "true\ntrue\nfalse"

    def test_string_substring(self):
        src = '''
            int main() {
                string s = "hello world";
                string sub = s.substring(6, 5);
                print(sub);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "world"

    def test_string_toUpper_toLower(self):
        src = '''
            int main() {
                string s = "Hello";
                print(s.toUpper());
                print(s.toLower());
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "HELLO\nhello"

    def test_string_trim(self):
        src = '''
            int main() {
                string s = "  hello  ";
                string t = s.trim();
                print(t);
                print(t.len());
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "hello\n5"

    def test_string_indexOf(self):
        src = '''
            int main() {
                string s = "hello world";
                print(s.indexOf("world"));
                print(s.indexOf("xyz"));
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "6\n-1"

    def test_string_charAt(self):
        src = '''
            #include <stdio.h>
            int main() {
                string s = "abcde";
                printf("%c\\n", s.charAt(2));
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "c"

    def test_string_equals(self):
        src = '''
            int main() {
                string a = "hello";
                string b = "hello";
                string c = "world";
                print(a.equals(b));
                print(a.equals(c));
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "true\nfalse"

    def test_string_replace(self):
        src = '''
            int main() {
                string s = "hello world";
                print(s.replace("world", "btrc"));
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "hello btrc"

    def test_string_lastIndexOf(self):
        src = '''
            int main() {
                string s = "abcabc";
                print(s.lastIndexOf("abc"));
                print(s.lastIndexOf("xyz"));
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "3\n-1"


class TestE2EListJoin:
    def test_join_basic(self):
        src = '''
            int main() {
                Vector<string> words = ["hello", "world", "btrc"];
                print(words.join(", "));
                words.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "hello, world, btrc"

    def test_join_single(self):
        src = '''
            int main() {
                Vector<string> words = ["only"];
                print(words.join("-"));
                words.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "only"

    def test_join_empty(self):
        src = '''
            #include <stdio.h>
            int main() {
                Vector<string> words = [];
                string result = words.join(",");
                printf("[%s]\\n", result);
                words.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "[]"


class TestE2EDefaultParams:
    def test_function_default_params(self):
        src = '''
            int add(int a, int b = 10) {
                return a + b;
            }
            int main() {
                print(add(5, 3));
                print(add(5));
                return 0;
            }
        '''
        output = compile_and_run(src).strip()
        assert output == "8\n15"

    def test_multiple_defaults(self):
        src = '''
            int compute(int a, int b = 2, int c = 3) {
                return a + b * c;
            }
            int main() {
                print(compute(1, 4, 5));
                print(compute(1, 4));
                print(compute(1));
                return 0;
            }
        '''
        output = compile_and_run(src).strip()
        assert output == "21\n13\n7"

    def test_constructor_defaults(self):
        src = '''
            class Rect {
                public int w;
                public int h;
                public Rect(int w = 100, int h = 50) {
                    self.w = w;
                    self.h = h;
                }
            }
            int main() {
                Rect a = Rect(10, 20);
                Rect b = Rect(10);
                Rect c = Rect();
                print(a.w, a.h);
                print(b.w, b.h);
                print(c.w, c.h);
                return 0;
            }
        '''
        output = compile_and_run(src).strip()
        assert output == "10 20\n10 50\n100 50"


class TestE2ETryCatch:
    def test_try_catch_basic(self):
        src = '''
            int main() {
                try {
                    throw "something went wrong";
                } catch (string e) {
                    print(f"caught: {e}");
                }
                return 0;
            }
        '''
        output = compile_and_run(src).strip()
        assert output == "caught: something went wrong"

    def test_try_catch_no_throw(self):
        src = '''
            int main() {
                try {
                    print("no error");
                } catch (string e) {
                    print("should not reach");
                }
                return 0;
            }
        '''
        output = compile_and_run(src).strip()
        assert output == "no error"

    def test_try_catch_function_throw(self):
        src = '''
            void risky(int x) {
                if (x < 0) {
                    throw "negative value";
                }
            }
            int main() {
                try {
                    risky(5);
                    print("ok");
                    risky(-1);
                    print("should not reach");
                } catch (string e) {
                    print(f"error: {e}");
                }
                return 0;
            }
        '''
        output = compile_and_run(src).strip()
        assert output == "ok\nerror: negative value"

    def test_try_catch_nested(self):
        src = '''
            int main() {
                try {
                    try {
                        throw "inner error";
                    } catch (string e) {
                        print(f"inner: {e}");
                    }
                    print("between");
                    throw "outer error";
                } catch (string e) {
                    print(f"outer: {e}");
                }
                return 0;
            }
        '''
        output = compile_and_run(src).strip()
        assert output == "inner: inner error\nbetween\nouter: outer error"


class TestE2EInheritance:
    def test_basic_inheritance(self):
        src = '''
            class Animal {
                public string name;
                public Animal(string name) {
                    self.name = name;
                }
                public string speak() {
                    return "...";
                }
            }
            class Dog extends Animal {
                public Dog(string name) {
                    self.name = name;
                }
                public string speak() {
                    return "Woof";
                }
            }
            int main() {
                Dog d = Dog("Rex");
                print(d.name);
                print(d.speak());
                return 0;
            }
        '''
        output = compile_and_run(src).strip()
        assert output == "Rex\nWoof"

    def test_inherited_method(self):
        src = '''
            class Shape {
                public int sides;
                public Shape(int sides) {
                    self.sides = sides;
                }
                public int getSides() {
                    return self.sides;
                }
            }
            class Triangle extends Shape {
                public Triangle() {
                    self.sides = 3;
                }
            }
            int main() {
                Triangle t = Triangle();
                print(t.getSides());
                return 0;
            }
        '''
        output = compile_and_run(src).strip()
        assert output == "3"

    def test_method_override(self):
        src = '''
            class Base {
                public int value;
                public Base(int v) {
                    self.value = v;
                }
                public int compute() {
                    return self.value;
                }
            }
            class Derived extends Base {
                public Derived(int v) {
                    self.value = v;
                }
                public int compute() {
                    return self.value * 2;
                }
            }
            int main() {
                Derived d = Derived(5);
                print(d.compute());
                return 0;
            }
        '''
        output = compile_and_run(src).strip()
        assert output == "10"

    def test_multi_level_inheritance(self):
        src = '''
            class A {
                public int x;
                public A(int x) {
                    self.x = x;
                }
                public int getX() {
                    return self.x;
                }
            }
            class B extends A {
                public int y;
                public B(int x, int y) {
                    self.x = x;
                    self.y = y;
                }
                public int getY() {
                    return self.y;
                }
            }
            class C extends B {
                public int z;
                public C(int x, int y, int z) {
                    self.x = x;
                    self.y = y;
                    self.z = z;
                }
                public int sum() {
                    return self.x + self.y + self.z;
                }
            }
            int main() {
                C c = C(1, 2, 3);
                print(c.getX());
                print(c.getY());
                print(c.sum());
                return 0;
            }
        '''
        output = compile_and_run(src).strip()
        assert output == "1\n2\n6"


class TestE2ENullable:
    def test_nullable_type(self):
        src = '''
            int main() {
                int* p = null;
                if (p == null) {
                    print("is null");
                }
                int x = 42;
                p = &x;
                printf("%d\\n", *p);
                return 0;
            }
        '''
        output = compile_and_run(src).strip()
        assert output == "is null\n42"

    def test_null_coalescing(self):
        src = '''
            int main() {
                char* name = null;
                char* result = name ?? "default";
                print(result);
                name = "Alex";
                result = name ?? "default";
                print(result);
                return 0;
            }
        '''
        output = compile_and_run(src).strip()
        assert output == "default\nAlex"

    def test_optional_chaining(self):
        src = '''
            struct Node {
                int value;
                struct Node* next;
            };
            int main() {
                struct Node b;
                b.value = 20;
                b.next = null;
                struct Node a;
                a.value = 10;
                a.next = &b;
                print(a.next?.value);
                print(a.next?.next?.value);
                return 0;
            }
        '''
        output = compile_and_run(src).strip()
        assert output == "20\n0"

    def test_nullable_class(self):
        src = '''
            class Box {
                public int val;
                public Box(int v) {
                    self.val = v;
                }
                public int getVal() {
                    return self.val;
                }
            }
            int main() {
                Box b = new Box(42);
                print(b?.val);
                delete b;
                b = null;
                print(b?.val);
                return 0;
            }
        '''
        output = compile_and_run(src).strip()
        assert output == "42\n0"


class TestE2EVarInference:
    def test_var_int(self):
        src = '''
            int main() {
                var x = 42;
                printf("%d\\n", x);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "42"

    def test_var_string(self):
        src = '''
            int main() {
                var s = "hello";
                printf("%s\\n", s);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "hello"

    def test_var_list(self):
        src = '''
            #include <stdio.h>
            int main() {
                var nums = [10, 20, 30];
                int sum = 0;
                for x in nums {
                    sum += x;
                }
                printf("%d\\n", sum);
                nums.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "60"

    def test_var_in_for_init(self):
        src = '''
            int main() {
                int sum = 0;
                for (var i = 0; i < 5; i++) {
                    sum += i;
                }
                printf("%d\\n", sum);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "10"

    def test_var_with_class_constructor(self):
        src = '''
            #include <stdio.h>
            class Point {
                public int x;
                public int y;
                public Point(int x, int y) {
                    self.x = x;
                    self.y = y;
                }
            }
            int main() {
                var p = Point(10, 20);
                printf("%d %d\\n", p.x, p.y);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "10 20"


class TestE2EMapMethods:
    def test_map_keys(self):
        src = '''
            #include <stdio.h>
            int main() {
                Map<int, int> m = {1: 10, 2: 20, 3: 30};
                Vector<int> k = m.keys();
                k.sort();
                for x in k {
                    printf("%d ", x);
                }
                printf("\\n");
                k.free();
                m.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "1 2 3"

    def test_map_values(self):
        src = '''
            #include <stdio.h>
            int main() {
                Map<int, int> m = {1: 10, 2: 20, 3: 30};
                Vector<int> v = m.values();
                v.sort();
                for x in v {
                    printf("%d ", x);
                }
                printf("\\n");
                v.free();
                m.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "10 20 30"

    def test_map_keys_string(self):
        src = '''
            #include <stdio.h>
            int main() {
                Map<string, int> m = {"a": 1, "b": 2};
                Vector<string> k = m.keys();
                printf("%d\\n", k.len);
                k.free();
                m.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "2"

    def test_map_values_string(self):
        src = '''
            #include <stdio.h>
            int main() {
                Map<string, int> m = {"x": 100, "y": 200};
                Vector<int> v = m.values();
                v.sort();
                for x in v {
                    printf("%d ", x);
                }
                printf("\\n");
                v.free();
                m.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "100 200"

    def test_map_remove(self):
        src = '''
            #include <stdio.h>
            int main() {
                Map<string, int> m = {"alice": 30, "bob": 25, "carol": 35};
                printf("%d\\n", m.len);
                m.remove("bob");
                printf("%d\\n", m.len);
                printf("%d\\n", m.has("bob"));
                printf("%d\\n", m.has("alice"));
                printf("%d\\n", m.get("alice"));
                printf("%d\\n", m.get("carol"));
                m.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "3\n2\n0\n1\n30\n35"

    def test_map_remove_int_keys(self):
        src = '''
            #include <stdio.h>
            int main() {
                Map<int, int> m = {1: 10, 2: 20, 3: 30, 4: 40};
                m.remove(2);
                m.remove(4);
                printf("%d\\n", m.len);
                printf("%d\\n", m.has(1));
                printf("%d\\n", m.has(2));
                printf("%d\\n", m.has(3));
                printf("%d\\n", m.has(4));
                printf("%d\\n", m.get(1));
                printf("%d\\n", m.get(3));
                m.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "2\n1\n0\n1\n0\n10\n30"

    def test_map_remove_then_reinsert(self):
        src = '''
            #include <stdio.h>
            int main() {
                Map<string, int> m = {"a": 1, "b": 2};
                m.remove("a");
                printf("%d\\n", m.has("a"));
                m.put("a", 99);
                printf("%d\\n", m.has("a"));
                printf("%d\\n", m.get("a"));
                m.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "0\n1\n99"

    def test_map_keys_values_len(self):
        """keys() and values() should have len == map.len."""
        src = '''
            #include <stdio.h>
            int main() {
                Map<int, int> m = {10: 100, 20: 200, 30: 300};
                Vector<int> k = m.keys();
                Vector<int> v = m.values();
                printf("%d %d %d\\n", m.len, k.len, v.len);
                k.free();
                v.free();
                m.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "3 3 3"


class TestE2EListIndexOf:
    def test_indexof_found(self):
        src = '''
            int main() {
                Vector<int> nums = [10, 20, 30, 40, 50];
                print(nums.indexOf(30));
                nums.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "2"

    def test_indexof_not_found(self):
        src = '''
            int main() {
                Vector<int> nums = [10, 20, 30];
                print(nums.indexOf(99));
                nums.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "-1"

    def test_indexof_first_occurrence(self):
        src = '''
            int main() {
                Vector<int> nums = [5, 10, 5, 10, 5];
                print(nums.indexOf(10));
                nums.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "1"

    def test_lastindexof_found(self):
        src = '''
            int main() {
                Vector<int> nums = [5, 10, 5, 10, 5];
                print(nums.lastIndexOf(10));
                nums.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "3"

    def test_lastindexof_not_found(self):
        src = '''
            int main() {
                Vector<int> nums = [1, 2, 3];
                print(nums.lastIndexOf(99));
                nums.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "-1"

    def test_indexof_float(self):
        src = '''
            #include <stdio.h>
            int main() {
                Vector<float> vals = [1.5, 2.5, 3.5, 2.5];
                printf("%d %d\\n", vals.indexOf(2.5), vals.lastIndexOf(2.5));
                vals.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "1 3"

    def test_indexof_empty_list(self):
        src = '''
            int main() {
                Vector<int> nums = [];
                print(nums.indexOf(1));
                print(nums.lastIndexOf(1));
                nums.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "-1\n-1"

    def test_indexof_single_element(self):
        src = '''
            int main() {
                Vector<int> nums = [42];
                print(nums.indexOf(42));
                print(nums.lastIndexOf(42));
                nums.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "0\n0"


class TestE2EListSlice:
    def test_list_slice_basic(self):
        src = '''
            #include <stdio.h>
            int main() {
                Vector<int> nums = [10, 20, 30, 40, 50];
                Vector<int> sub = nums.slice(1, 4);
                for x in sub {
                    printf("%d ", x);
                }
                printf("\\n");
                sub.free();
                nums.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "20 30 40"

    def test_list_slice_from_start(self):
        src = '''
            int main() {
                Vector<int> nums = [1, 2, 3, 4, 5];
                Vector<int> sub = nums.slice(0, 3);
                print(sub.len);
                sub.free();
                nums.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "3"

    def test_list_slice_empty(self):
        src = '''
            int main() {
                Vector<int> nums = [1, 2, 3];
                Vector<int> sub = nums.slice(2, 2);
                print(sub.len);
                sub.free();
                nums.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "0"


class TestE2EStdlibMath:
    MATH_CLASS = '''
        #include <stdio.h>
        #include <math.h>
        class Math {
            class int abs(int x) {
                if (x < 0) { return -x; }
                return x;
            }
            class int max(int a, int b) {
                if (a > b) { return a; }
                return b;
            }
            class int min(int a, int b) {
                if (a < b) { return a; }
                return b;
            }
            class float pow(float base, float exp) {
                return powf(base, exp);
            }
            class float sqrt(float x) {
                return sqrtf(x);
            }
        }
    '''

    def test_math_abs(self):
        src = self.MATH_CLASS + '''
            int main() {
                printf("%d\\n", Math.abs(-5));
                printf("%d\\n", Math.abs(3));
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "5\n3"

    def test_math_max_min(self):
        src = self.MATH_CLASS + '''
            int main() {
                printf("%d\\n", Math.max(3, 7));
                printf("%d\\n", Math.min(3, 7));
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "7\n3"

    def test_math_pow(self):
        src = self.MATH_CLASS + '''
            int main() {
                printf("%.0f\\n", Math.pow(2.0, 10.0));
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "1024"

    def test_math_sqrt(self):
        src = self.MATH_CLASS + '''
            int main() {
                printf("%.1f\\n", Math.sqrt(25.0));
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "5.0"


class TestE2EStaticMethods:
    def test_static_method_call(self):
        src = '''
            class Utils {
                class int twice(int x) {
                    return x * 2;
                }
                class int square(int x) {
                    return x * x;
                }
            }
            int main() {
                print(Utils.twice(5));
                print(Utils.square(4));
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "10\n16"

    def test_static_method_string_return(self):
        src = '''
            #include <string.h>
            #include <stdio.h>
            class Greeter {
                class string greet(string name) {
                    return f"Hello, {name}!";
                }
            }
            int main() {
                printf("%s\\n", Greeter.greet("world"));
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "Hello, world!"

    def test_map_iteration_kv(self):
        src = '''
            int main() {
                Map<string, int> ages = {};
                ages.put("alice", 30);
                ages.put("bob", 25);
                int total = 0;
                for name, age in ages {
                    total = total + age;
                }
                print(total);
                return 0;
            }
        '''
        output = compile_and_run(src).strip()
        assert output == "55"

    def test_map_iteration_keys_only(self):
        src = '''
            int main() {
                Map<int, int> m = {};
                m.put(10, 100);
                m.put(20, 200);
                int sum = 0;
                for k in m {
                    sum = sum + k;
                }
                print(sum);
                return 0;
            }
        '''
        output = compile_and_run(src).strip()
        assert output == "30"

    def test_static_method_chain(self):
        src = '''
            class Counter {
                class int add(int a, int b) {
                    return a + b;
                }
                class int negate(int x) {
                    return -x;
                }
            }
            int main() {
                print(Counter.negate(Counter.add(3, 7)));
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "-10"

    def test_pointer_method_call(self):
        src = '''
            class Bag {
                public Vector<int> items = [];

                public void add(int x) {
                    self.items.push(x);
                }

                public int count() {
                    return self.items.len;
                }
            }
            int main() {
                Bag b = new Bag();
                b.add(10);
                b.add(20);
                b.add(30);
                print(b.count());
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "3"

    def test_pointer_field_access(self):
        src = '''
            class Point {
                public int x = 0;
                public int y = 0;

                public void set(int nx, int ny) {
                    self.x = nx;
                    self.y = ny;
                }
            }
            int main() {
                Point p = new Point();
                p.set(10, 20);
                print(p.x + p.y);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "30"

    def test_pointer_map_field(self):
        src = '''
            class Store {
                public Map<string, int> inventory = {};

                public void stock(string item, int qty) {
                    self.inventory.put(item, qty);
                }
            }
            int main() {
                Store s = new Store();
                s.stock("apples", 50);
                s.stock("bananas", 30);
                print(s.inventory.len);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "2"

    def test_empty_brace_map_init(self):
        src = '''
            int main() {
                Map<string, int> m = {};
                m.put("a", 1);
                m.put("b", 2);
                print(m.len);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "2"

    def test_list_bounds_check(self):
        src = '''
            int main() {
                Vector<int> nums = [10, 20, 30];
                print(nums.get(0));
                print(nums.get(2));
                return 0;
            }
        '''
        output = compile_and_run(src).strip()
        assert "10" in output
        assert "30" in output

    def test_inheritance_method_call(self):
        src = '''
            class Animal {
                public string name = "";
                public string speak() {
                    return "...";
                }
            }
            class Dog extends Animal {
                public string speak() {
                    return "Woof!";
                }
            }
            int main() {
                Dog d = Dog();
                d.name = "Rex";
                print(d.speak());
                print(d.name);
                return 0;
            }
        '''
        output = compile_and_run(src).strip().split('\n')
        assert output[0] == "Woof!"
        assert output[1] == "Rex"

    def test_nested_collection_operations(self):
        src = '''
            int main() {
                Vector<int> a = [1, 2, 3, 4, 5];
                a.reverse();
                a.remove(0);
                print(a.get(0));
                print(a.len);
                return 0;
            }
        '''
        output = compile_and_run(src).strip().split('\n')
        assert output[0] == "4"
        assert output[1] == "4"

    def test_class_with_map_and_list_fields(self):
        src = '''
            class Registry {
                public Map<string, int> scores = {};
                public Vector<string> names = [];

                public void add(string name, int score) {
                    self.names.push(name);
                    self.scores.put(name, score);
                }

                public int total() {
                    int sum = 0;
                    for n, s in self.scores {
                        sum = sum + s;
                    }
                    return sum;
                }
            }
            int main() {
                Registry r = Registry();
                r.add("alice", 90);
                r.add("bob", 85);
                print(r.names.len);
                print(r.total());
                return 0;
            }
        '''
        output = compile_and_run(src).strip().split('\n')
        assert output[0] == "2"
        assert output[1] == "175"

    def test_default_params(self):
        src = '''
            string greet(string name, string greeting = "Hello") {
                return f"{greeting}, {name}!";
            }
            int main() {
                print(greet("World"));
                print(greet("btrc", "Hey"));
                return 0;
            }
        '''
        output = compile_and_run(src).strip().split('\n')
        assert output[0] == "Hello, World!"
        assert output[1] == "Hey, btrc!"

    def test_try_catch(self):
        src = '''
            int main() {
                try {
                    throw "something went wrong";
                } catch (e) {
                    print(e);
                }
                print("recovered");
                return 0;
            }
        '''
        output = compile_and_run(src).strip().split('\n')
        assert output[0] == "something went wrong"
        assert output[1] == "recovered"

    def test_do_while(self):
        src = '''
            int main() {
                int x = 0;
                do {
                    x = x + 1;
                } while (x < 5);
                print(x);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "5"

    def test_switch_case(self):
        src = '''
            int main() {
                int x = 2;
                switch (x) {
                    case 1:
                        print("one");
                        break;
                    case 2:
                        print("two");
                        break;
                    default:
                        print("other");
                        break;
                }
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "two"


class TestE2ESetOperations:
    def test_set_basic_ops(self):
        src = '''
            int main() {
                Set<int> s = {};
                s.add(1);
                s.add(2);
                s.add(3);
                s.add(2);
                print(s.size());
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "3"

    def test_set_contains(self):
        src = '''
            int main() {
                Set<int> s = {};
                s.add(10);
                s.add(20);
                if (s.contains(10)) { print("yes"); }
                if (!s.contains(99)) { print("no"); }
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "yes\nno"

    def test_set_remove(self):
        src = '''
            int main() {
                Set<int> s = {};
                s.add(1);
                s.add(2);
                s.add(3);
                s.remove(2);
                print(s.size());
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "2"

    def test_set_to_list(self):
        src = '''
            int main() {
                Set<int> s = {};
                s.add(42);
                Vector<int> lst = s.toVector();
                print(lst.size());
                print(lst.get(0));
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "1\n42"

    def test_set_isEmpty(self):
        src = '''
            int main() {
                Set<int> s = {};
                if (s.isEmpty()) { print("empty"); }
                s.add(1);
                if (!s.isEmpty()) { print("not empty"); }
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "empty\nnot empty"


class TestE2ENestedGenerics:
    def test_list_of_strings(self):
        """Test Vector<string> which is a generic containing another generic-like type."""
        src = '''
            int main() {
                Vector<string> names = ["alice", "bob", "carol"];
                print(names.size());
                print(names.get(1));
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "3\nbob"

    def test_set_of_strings(self):
        src = '''
            int main() {
                Set<string> s = {};
                s.add("hello");
                s.add("world");
                s.add("hello");
                print(s.size());
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "2"


class TestE2ELambdas:
    def test_lambda_verbose(self):
        src = '''
            int main() {
                Vector<int> nums = [1, 2, 3, 4, 5];
                Vector<int> evens = nums.filter(bool function(int x) { return x % 2 == 0; });
                print(evens.size());
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "2"

    def test_lambda_arrow(self):
        src = '''
            int main() {
                Vector<int> nums = [1, 2, 3, 4, 5];
                Vector<int> evens = nums.filter((int x) => x % 2 == 0);
                print(evens.size());
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "2"

    def test_lambda_with_map(self):
        src = '''
            int main() {
                Vector<int> nums = [1, 2, 3];
                Vector<int> doubled = nums.map(int function(int x) { return x * 2; });
                print(doubled.get(0));
                print(doubled.get(1));
                print(doubled.get(2));
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "2\n4\n6"


class TestE2EUserDefinedGenerics:
    def test_simple_generic_class(self):
        src = '''
            class Box<T> {
                public T value;
                public Box(T val) { self.value = val; }
                public T get() { return self.value; }
            }
            int main() {
                Box<int> b = Box(42);
                print(b.get());
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "42"

    def test_generic_class_multiple_instantiations(self):
        src = '''
            class Box<T> {
                public T value;
                public Box(T val) { self.value = val; }
                public T get() { return self.value; }
            }
            int main() {
                Box<int> a = Box(10);
                Box<string> b = Box("hello");
                print(a.get());
                print(b.get());
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "10\nhello"

    def test_generic_class_two_params(self):
        src = '''
            class Pair<A, B> {
                public A first;
                public B second;
                public Pair(A a, B b) { self.first = a; self.second = b; }
                public A getFirst() { return self.first; }
                public B getSecond() { return self.second; }
            }
            int main() {
                Pair<string, int> p = Pair("x", 42);
                print(p.getFirst());
                print(p.getSecond());
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "x\n42"

    def test_generic_class_with_method(self):
        src = '''
            class Container<T> {
                public T item;
                public Container(T val) { self.item = val; }
                public void set(T val) { self.item = val; }
                public T get() { return self.item; }
            }
            int main() {
                Container<int> c = Container(1);
                c.set(99);
                print(c.get());
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "99"


class TestE2ERichEnums:
    def test_rich_enum_basic(self):
        src = '''
            enum class Color {
                RGB(int r, int g, int b),
                Named(string name)
            }
            int main() {
                Color c = Color.RGB(255, 0, 0);
                if (c.tag == Color.RGB) {
                    print(c.data.RGB.r);
                }
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "255"

    def test_rich_enum_multiple_variants(self):
        src = '''
            enum class Shape {
                Circle(double radius),
                Rect(double w, double h),
                Point
            }
            int main() {
                Shape s = Shape.Circle(5.0);
                Shape r = Shape.Rect(3.0, 4.0);
                Shape p = Shape.Point();
                if (s.tag == Shape.Circle) { print("circle"); }
                if (r.tag == Shape.Rect) { print("rect"); }
                if (p.tag == Shape.Point) { print("point"); }
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "circle\nrect\npoint"

    def test_rich_enum_toString(self):
        src = '''
            enum class Direction {
                North,
                South,
                East,
                West
            }
            int main() {
                Direction d = Direction.North();
                string name = Direction_toString(d);
                print(name);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "North"


class TestE2EInterfaces:
    def test_basic_interface(self):
        src = '''
            interface Greeter {
                string greet();
            }
            class Dog implements Greeter {
                public string name;
                public Dog(string name) { self.name = name; }
                public string greet() { return "Woof"; }
            }
            int main() {
                Dog d = Dog("Rex");
                print(d.greet());
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "Woof"

    def test_multiple_interface_methods(self):
        src = '''
            interface Describable {
                string name();
                int age();
            }
            class Person implements Describable {
                public string _name;
                public int _age;
                public Person(string n, int a) { self._name = n; self._age = a; }
                public string name() { return self._name; }
                public int age() { return self._age; }
            }
            int main() {
                Person p = Person("Alice", 30);
                print(p.name());
                print(p.age());
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "Alice\n30"

    def test_interface_with_extends(self):
        src = '''
            interface HasName {
                string name();
            }
            interface HasFullName extends HasName {
                string fullName();
            }
            class Employee implements HasFullName {
                public string first;
                public string last;
                public Employee(string f, string l) { self.first = f; self.last = l; }
                public string name() { return self.first; }
                public string fullName() { return self.first; }
            }
            int main() {
                Employee e = Employee("Bob", "Smith");
                print(e.name());
                print(e.fullName());
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "Bob\nBob"


class TestE2EAbstractClasses:
    def test_abstract_class(self):
        src = '''
            abstract class Shape {
                public abstract double area();
                public string kind() { return "shape"; }
            }
            class Circle extends Shape {
                public double r;
                public Circle(double r) { self.r = r; }
                public double area() { return 3.14 * self.r * self.r; }
            }
            int main() {
                Circle c = Circle(1.0);
                print(c.area());
                print(c.kind());
                return 0;
            }
        '''
        output = compile_and_run(src).strip().split('\n')
        assert output[0].startswith("3.14")
        assert output[1] == "shape"

    def test_abstract_multiple_subclasses(self):
        src = '''
            abstract class Animal {
                public abstract string speak();
            }
            class Cat extends Animal {
                public Cat() {}
                public string speak() { return "Meow"; }
            }
            class Duck extends Animal {
                public Duck() {}
                public string speak() { return "Quack"; }
            }
            int main() {
                Cat c = Cat();
                Duck d = Duck();
                print(c.speak());
                print(d.speak());
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "Meow\nQuack"

    def test_abstract_cannot_instantiate(self):
        src = '''
            abstract class Base {
                public abstract int value();
            }
            int main() {
                Base b = Base();
                return 0;
            }
        '''
        errors = compile_and_check_errors(src)
        assert any("Cannot instantiate abstract class" in e for e in errors)


class TestE2EEnums:
    def test_basic_enum(self):
        src = '''
            enum Color { RED, GREEN, BLUE };
            int main() {
                int c = GREEN;
                print(c);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "1"

    def test_enum_in_switch(self):
        src = '''
            enum Day { MON, TUE, WED, THU, FRI, SAT, SUN };
            int main() {
                int d = WED;
                switch (d) {
                    case MON: print("Monday"); break;
                    case WED: print("Wednesday"); break;
                    default: print("other"); break;
                }
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "Wednesday"

    def test_enum_toString(self):
        src = '''
            enum Color { RED, GREEN, BLUE };
            int main() {
                Color c = GREEN;
                string s = c.toString();
                print(s);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "GREEN"

    def test_enum_toString_with_values(self):
        src = '''
            enum Level { LOW = 1, MEDIUM = 5, HIGH = 10 };
            int main() {
                Level lv = HIGH;
                print(lv.toString());
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "HIGH"

    def test_enum_toString_in_fstring(self):
        src = '''
            enum Fruit { APPLE, BANANA, CHERRY };
            int main() {
                Fruit f = BANANA;
                string msg = f"fruit: {f.toString()}";
                print(msg);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "fruit: BANANA"


class TestE2ENumericToString:
    def test_int_toString(self):
        src = '''
            int main() {
                int n = 42;
                string s = n.toString();
                print(s);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "42"

    def test_float_toString(self):
        src = '''
            int main() {
                float f = 3.14;
                string s = f.toString();
                print(s);
                return 0;
            }
        '''
        output = compile_and_run(src).strip()
        assert output.startswith("3.14")

    def test_bool_toString(self):
        src = '''
            int main() {
                bool b = true;
                string s = b.toString();
                print(s);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "true"


class TestE2EStringZfill:
    def test_zfill_basic(self):
        src = '''
            int main() {
                string s = "42";
                string z = s.zfill(5);
                print(z);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "00042"

    def test_zfill_with_sign(self):
        src = '''
            int main() {
                string s = "-42";
                string z = s.zfill(6);
                print(z);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "-00042"


class TestE2EListTakeDrop:
    def test_take(self):
        src = '''
            int main() {
                Vector<int> a = [1, 2, 3, 4, 5];
                Vector<int> t = a.take(3);
                print(t.size());
                print(t.get(0));
                print(t.get(2));
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "3\n1\n3"

    def test_drop(self):
        src = '''
            int main() {
                Vector<int> a = [1, 2, 3, 4, 5];
                Vector<int> d = a.drop(2);
                print(d.size());
                print(d.get(0));
                print(d.get(2));
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "3\n3\n5"


class TestE2EListReversed:
    def test_reversed(self):
        src = '''
            int main() {
                Vector<int> a = [1, 2, 3, 4, 5];
                Vector<int> r = a.reversed();
                print(r.get(0));
                print(r.get(4));
                // original unchanged
                print(a.get(0));
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "5\n1\n1"


class TestE2EMapContainsValue:
    def test_containsValue(self):
        src = '''
            int main() {
                Map<string, int> m = {};
                m.put("x", 10);
                m.put("y", 20);
                if (m.containsValue(10)) { print("found 10"); }
                if (!m.containsValue(99)) { print("no 99"); }
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "found 10\nno 99"


class TestE2EListFindIndex:
    def test_findIndex(self):
        src = '''
            bool isEven(int x) { return x % 2 == 0; }
            int main() {
                Vector<int> a = [1, 3, 4, 7, 8];
                int idx = a.findIndex(isEven);
                print(idx);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "2"

    def test_findIndex_not_found(self):
        src = '''
            bool isNeg(int x) { return x < 0; }
            int main() {
                Vector<int> a = [1, 2, 3];
                int idx = a.findIndex(isNeg);
                print(idx);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "-1"


class TestE2EStringConversions:
    def test_toDouble(self):
        src = '''
            int main() {
                string s = "3.14";
                double d = s.toDouble();
                if (d > 3.0) { print("yes"); }
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "yes"

    def test_toLong(self):
        src = '''
            int main() {
                string s = "99999";
                long n = s.toLong();
                print(n);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "99999"


class TestE2EBitwiseOps:
    def test_bitwise_and(self):
        src = '''
            int main() {
                int a = 0xFF;
                int b = 0x0F;
                print(a & b);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "15"

    def test_bitwise_or(self):
        src = '''
            int main() {
                int a = 0xF0;
                int b = 0x0F;
                print(a | b);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "255"

    def test_bitwise_xor(self):
        src = '''
            int main() {
                int a = 0xFF;
                int b = 0x0F;
                print(a ^ b);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "240"

    def test_left_shift(self):
        src = '''
            int main() {
                int a = 1;
                print(a << 4);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "16"

    def test_right_shift(self):
        src = '''
            int main() {
                int a = 256;
                print(a >> 4);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "16"

    def test_bitwise_not(self):
        src = '''
            int main() {
                int a = 0;
                print(~a);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "-1"


class TestE2EOctalLiterals:
    def test_octal_value(self):
        src = '''
            int main() {
                int x = 0o10;
                print(x);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "8"

    def test_octal_permissions(self):
        src = '''
            int main() {
                int perms = 0o755;
                print(perms);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "493"


class TestE2ESizeof:
    def test_sizeof_int(self):
        src = '''
            int main() {
                int s = sizeof(int);
                if (s > 0) { print("ok"); }
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "ok"

    def test_sizeof_double(self):
        src = '''
            int main() {
                int s = sizeof(double);
                print(s);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "8"


class TestE2EFStringMethodCalls:
    def test_fstring_with_list_size(self):
        src = '''
            int main() {
                Vector<int> nums = [1, 2, 3];
                print(f"size: {nums.size()}");
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "size: 3"

    def test_fstring_with_string_method(self):
        src = '''
            int main() {
                string s = "hello";
                print(f"upper: {s.toUpper()}");
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "upper: HELLO"


class TestE2EFStringBraceEscape:
    def test_literal_braces(self):
        src = '''
            int main() {
                int x = 42;
                print(f"value: {{x}} = {x}");
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "value: {x} = 42"

    def test_braces_in_code_gen(self):
        src = '''
            int main() {
                string name = "test";
                string code = f"void {name}() {{}}";
                print(code);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "void test() {}"


class TestE2EResultType:
    def test_result_ok(self):
        src = '''
            class Result<T, E> {
                private bool _ok;
                private T _value;
                private E _error;

                public Result(bool ok, T value, E error) {
                    self._ok = ok;
                    self._value = value;
                    self._error = error;
                }

                public bool isOk() { return self._ok; }
                public bool isErr() { return !self._ok; }
                public T unwrap() { return self._value; }
                public E unwrapErr() { return self._error; }
            }

            int main() {
                Result<int, string> r = new Result<int, string>(true, 42, "");
                if (r.isOk()) {
                    print(r.unwrap());
                }
                if (!r.isErr()) {
                    print("not an error");
                }
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "42\nnot an error"

    def test_result_err(self):
        src = '''
            class Result<T, E> {
                private bool _ok;
                private T _value;
                private E _error;

                public Result(bool ok, T value, E error) {
                    self._ok = ok;
                    self._value = value;
                    self._error = error;
                }

                public bool isOk() { return self._ok; }
                public bool isErr() { return !self._ok; }
                public T unwrap() { return self._value; }
                public E unwrapErr() { return self._error; }
            }

            int main() {
                Result<int, string> e = new Result<int, string>(false, 0, "not found");
                if (e.isErr()) {
                    print(e.unwrapErr());
                }
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "not found"

    def test_result_multiple_types(self):
        src = '''
            class Result<T, E> {
                private bool _ok;
                private T _value;
                private E _error;

                public Result(bool ok, T value, E error) {
                    self._ok = ok;
                    self._value = value;
                    self._error = error;
                }

                public bool isOk() { return self._ok; }
                public bool isErr() { return !self._ok; }
                public T unwrap() { return self._value; }
                public E unwrapErr() { return self._error; }
            }

            int main() {
                Result<string, int> r1 = new Result<string, int>(true, "hello", 0);
                Result<float, string> r2 = new Result<float, string>(true, 3.14, "");
                print(r1.unwrap());
                float val = r2.unwrap();
                if (val > 3.0) {
                    print("ok");
                }
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "hello\nok"
