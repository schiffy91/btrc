#ifndef BTRC_APP_WINDOW_INTERNAL_H
#define BTRC_APP_WINDOW_INTERNAL_H

typedef struct GLFWwindow GLFWwindow;

/* Owner-thread only; keeps logical content dimensions and native controls. */
int btrc_app_platform_set_titlebar_style(GLFWwindow* window, int style);

#endif
