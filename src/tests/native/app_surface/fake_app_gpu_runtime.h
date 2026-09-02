#ifndef FAKE_APP_GPU_RUNTIME_H
#define FAKE_APP_GPU_RUNTIME_H

void fake_platform_reset(void);
void fake_platform_push_pointer(
    int action, int button, float x, float y, int modifiers);
void fake_platform_push_scroll(float x, float y);
void fake_platform_push_keyboard(int action, int key, int modifiers);
void fake_platform_push_text(char* text);
void fake_platform_push_surface(
    int kind,
    int logical_width,
    int logical_height,
    int framebuffer_width,
    int framebuffer_height,
    float scale_x,
    float scale_y);
void fake_platform_push_close(void);
void fake_platform_set_directory_picker(int outcome, char* directory, int error);
char* fake_platform_directory_picker_title(void);
char* fake_platform_directory_picker_initial_directory(void);
void fake_platform_expire_surface(unsigned long long surface);
void fake_gpu_fail_next_attach(int status);
void fake_gpu_malformed_next_attach(int status, int publish_handle);
void fake_gpu_set_next_frame(int status);
void fake_gpu_set_next_draw(int status);
void fake_gpu_set_device_lost(int lost);
void fake_gpu_set_next_resource_result(
    int status, int publish_identity, int publish_receipt);
int fake_native_ui_upload_count(void);
int fake_native_ui_first_rect_red(void);
int fake_native_ui_first_rect_green(void);
int fake_native_ui_first_rect_blue(void);
int fake_native_ui_first_rect_alpha(void);
int fake_gpu_frame_begin_count(void);
int fake_gpu_frame_present_count(void);
char* fake_platform_lifecycle(void);
int fake_platform_live_resources(void);
void fake_platform_worker_hold(void);
void fake_platform_wait_worker_ready(void);
void fake_platform_release_worker(void);

#endif
