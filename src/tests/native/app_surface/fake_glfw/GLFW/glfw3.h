#ifndef BTRC_TEST_GLFW3_H
#define BTRC_TEST_GLFW3_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct GLFWwindow GLFWwindow;
typedef struct GLFWmonitor GLFWmonitor;

typedef void (*GLFWcursorposfun)(GLFWwindow*, double, double);
typedef void (*GLFWmousebuttonfun)(GLFWwindow*, int, int, int);
typedef void (*GLFWscrollfun)(GLFWwindow*, double, double);
typedef void (*GLFWkeyfun)(GLFWwindow*, int, int, int, int);
typedef void (*GLFWcharfun)(GLFWwindow*, unsigned int);
typedef void (*GLFWwindowsizefun)(GLFWwindow*, int, int);
typedef void (*GLFWframebuffersizefun)(GLFWwindow*, int, int);
typedef void (*GLFWwindowcontentscalefun)(GLFWwindow*, float, float);
typedef void (*GLFWwindowclosefun)(GLFWwindow*);

#define GLFW_FALSE 0
#define GLFW_TRUE 1

#define GLFW_RELEASE 0
#define GLFW_PRESS 1
#define GLFW_REPEAT 2

#define GLFW_CLIENT_API 0x00022001
#define GLFW_NO_API 0
#define GLFW_RESIZABLE 0x00020003

#define GLFW_MOUSE_BUTTON_LEFT 0
#define GLFW_MOUSE_BUTTON_RIGHT 1
#define GLFW_MOUSE_BUTTON_MIDDLE 2

#define GLFW_MOD_SHIFT 0x0001
#define GLFW_MOD_CONTROL 0x0002
#define GLFW_MOD_ALT 0x0004
#define GLFW_MOD_SUPER 0x0008

#define GLFW_KEY_SPACE 32
#define GLFW_KEY_A 65
#define GLFW_KEY_D 68
#define GLFW_KEY_S 83
#define GLFW_KEY_W 87
#define GLFW_KEY_ESCAPE 256
#define GLFW_KEY_ENTER 257
#define GLFW_KEY_TAB 258
#define GLFW_KEY_BACKSPACE 259
#define GLFW_KEY_RIGHT 262
#define GLFW_KEY_LEFT 263
#define GLFW_KEY_DOWN 264
#define GLFW_KEY_UP 265
#define GLFW_KEY_LEFT_SHIFT 340
#define GLFW_KEY_LEFT_CONTROL 341
#define GLFW_KEY_LEFT_ALT 342
#define GLFW_KEY_LEFT_SUPER 343
#define GLFW_KEY_RIGHT_SHIFT 344
#define GLFW_KEY_RIGHT_CONTROL 345
#define GLFW_KEY_RIGHT_ALT 346
#define GLFW_KEY_RIGHT_SUPER 347

int glfwInit(void);
void glfwTerminate(void);
void glfwWindowHint(int hint, int value);
GLFWwindow* glfwCreateWindow(
    int width, int height, const char* title,
    GLFWmonitor* monitor, GLFWwindow* share);
void glfwDestroyWindow(GLFWwindow* window);
void glfwSetWindowUserPointer(GLFWwindow* window, void* pointer);
void* glfwGetWindowUserPointer(GLFWwindow* window);
GLFWcursorposfun glfwSetCursorPosCallback(
    GLFWwindow* window, GLFWcursorposfun callback);
GLFWmousebuttonfun glfwSetMouseButtonCallback(
    GLFWwindow* window, GLFWmousebuttonfun callback);
GLFWscrollfun glfwSetScrollCallback(
    GLFWwindow* window, GLFWscrollfun callback);
GLFWkeyfun glfwSetKeyCallback(GLFWwindow* window, GLFWkeyfun callback);
GLFWcharfun glfwSetCharCallback(GLFWwindow* window, GLFWcharfun callback);
GLFWwindowsizefun glfwSetWindowSizeCallback(
    GLFWwindow* window, GLFWwindowsizefun callback);
GLFWframebuffersizefun glfwSetFramebufferSizeCallback(
    GLFWwindow* window, GLFWframebuffersizefun callback);
GLFWwindowcontentscalefun glfwSetWindowContentScaleCallback(
    GLFWwindow* window, GLFWwindowcontentscalefun callback);
GLFWwindowclosefun glfwSetWindowCloseCallback(
    GLFWwindow* window, GLFWwindowclosefun callback);
void glfwGetCursorPos(GLFWwindow* window, double* x, double* y);
int glfwGetKey(GLFWwindow* window, int key);
void glfwGetWindowSize(GLFWwindow* window, int* width, int* height);
void glfwGetFramebufferSize(GLFWwindow* window, int* width, int* height);
void glfwGetWindowContentScale(GLFWwindow* window, float* x, float* y);
void glfwWaitEventsTimeout(double timeout);

#ifdef __cplusplus
}
#endif

#endif
