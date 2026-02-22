"""End-to-end tests for the btrc transpiler.

Each test: btrc source → lexer → parser → analyzer → codegen → gcc → run → check output.
"""

import subprocess
import tempfile
import os

import pytest
from compiler.python.lexer import Lexer
from compiler.python.parser import Parser
from compiler.python.analyzer import Analyzer
from compiler.python.codegen import CodeGen


def compile_and_run(btrc_source: str, extra_flags: list[str] = None) -> str:
    """Transpile btrc source to C, compile with gcc, run, return stdout."""
    tokens = Lexer(btrc_source).tokenize()
    program = Parser(tokens).parse()
    analyzed = Analyzer().analyze(program)
    assert not analyzed.errors, f"Analyzer errors: {analyzed.errors}"
    c_source = CodeGen(analyzed).generate()

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
                Node* n = new Node(99);
                printf("%d\\n", n->val);
                free(n);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "99"


class TestE2EList:
    def test_list_basic(self):
        src = '''
            #include <stdio.h>
            int main() {
                List<int> nums = [10, 20, 30];
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
                List<int> nums = [];
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
                Box* b = new Box(42);
                printf("%d\\n", b->get());
                free(b);
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "42"

    def test_list_dot_methods(self):
        src = '''
            #include <stdio.h>
            int main() {
                List<int> nums = [];
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
                List<int> nums = [10, 20, 30];
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
                List<int> nums = [1, 2, 3];
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
                public Vec2 __add__(Vec2* other) {
                    return Vec2(self.x + other->x, self.y + other->y);
                }
                public bool __eq__(Vec2* other) {
                    return self.x == other->x && self.y == other->y;
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
                List<int> nums = [5, 2, 8, 1, 9, 3];
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
                List<int> nums = [1, 2, 3, 4, 5];
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
                List<int> nums = [10, 20, 30];
                print(nums.contains(20));
                print(nums.contains(99));
                nums.free();
                return 0;
            }
        '''
        assert compile_and_run(src).strip() == "1\n0"

    def test_list_remove(self):
        src = '''
            #include <stdio.h>
            int main() {
                List<int> nums = [10, 20, 30, 40];
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
                List<int> nums = [1, 2, 3];
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
        assert compile_and_run(src).strip() == "1\n1\n0"

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
        assert compile_and_run(src).strip() == "1\n0"


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
                Box* b = new Box(42);
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
