#include "btrc_gpu_native_ui_internal.h"

#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#ifndef BTRC_NATIVE_UI_MAX_IMAGES
#define BTRC_NATIVE_UI_MAX_IMAGES 1024
#endif
#ifndef BTRC_NATIVE_UI_MAX_IMAGE_PIXELS
#define BTRC_NATIVE_UI_MAX_IMAGE_PIXELS UINT64_C(67108864)
#endif

enum {
    UI_MAX_COMMANDS = 16384,
    UI_MAX_ORDER = 32768,
    UI_MAX_IMAGES = BTRC_NATIVE_UI_MAX_IMAGES,
    UI_MAX_IMAGE_DIMENSION = 4096,
};

static const uint64_t UI_MAX_IMAGE_PIXELS =
    (uint64_t)BTRC_NATIVE_UI_MAX_IMAGE_PIXELS;

#ifdef BTRC_GPU_NATIVE_UI_CACHE_TEST
static bool native_ui_test_fail_create;
static bool native_ui_test_fail_upload;
static int native_ui_test_uploads;
#endif

typedef struct {
    float rect[4];
    float color[4];
    float meta0[4];
    float meta1[4];
    float meta2[4];
    float viewport[4];
} BtrcNativeUiCommand;

typedef struct {
    uint32_t kind;
    uint32_t index;
    uint32_t placement;
} BtrcNativeUiOrder;

typedef struct {
    float rect[4];
    float viewport[4];
} BtrcNativeUiImagePlacement;

typedef struct {
    char* identity;
    int width;
    int height;
    uint64_t last_used_generation;
    const unsigned char* source_identity;
    uint64_t source_revision;
    WGPUTexture texture;
    WGPUTextureView view;
    WGPUBindGroup bind_group;
} BtrcNativeUiImage;

typedef struct {
    WGPUDevice device;
    WGPUQueue queue;
    WGPURenderPipeline command_pipeline;
    WGPURenderPipeline image_pipeline;
    WGPUBuffer command_buffer;
    WGPUBuffer placement_buffer;
    WGPUBindGroup command_bind_group;
    WGPUSampler image_sampler;
    BtrcNativeUiCommand* commands;
    BtrcNativeUiImagePlacement* placements;
    BtrcNativeUiOrder* order;
    BtrcNativeUiImage* images;
    int command_count;
    int order_count;
    int placement_count;
    int image_count;
    int logical_width;
    int logical_height;
    uint64_t generation;
    uint64_t cached_image_pixels;
    uint64_t frame_image_pixels;
} BtrcNativeUi;

#ifndef BTRC_GPU_NATIVE_UI_CACHE_TEST
static const char* native_ui_wgsl =
    "struct UiCommand {\n"
    "  rect: vec4f,\n"
    "  color: vec4f,\n"
    "  meta0: vec4f,\n"
    "  meta1: vec4f,\n"
    "  meta2: vec4f,\n"
    "  viewport: vec4f,\n"
    "}\n"
    "@group(0) @binding(0) var<storage, read> commands: array<UiCommand>;\n"
    "struct CommandOut {\n"
    "  @builtin(position) position: vec4f,\n"
    "  @location(0) uv: vec2f,\n"
    "  @location(1) @interpolate(flat) color: vec4f,\n"
    "  @location(2) @interpolate(flat) size: vec2f,\n"
    "  @location(3) @interpolate(flat) meta0: vec4f,\n"
    "  @location(4) @interpolate(flat) meta1: vec4f,\n"
    "  @location(5) @interpolate(flat) meta2: vec4f,\n"
    "}\n"
    "fn corner(index: u32) -> vec2f {\n"
    "  let corners = array<vec2f, 6>(\n"
    "    vec2f(0.0, 0.0), vec2f(1.0, 0.0), vec2f(0.0, 1.0),\n"
    "    vec2f(0.0, 1.0), vec2f(1.0, 0.0), vec2f(1.0, 1.0));\n"
    "  return corners[index];\n"
    "}\n"
    "@vertex fn vs_command(\n"
    "    @builtin(vertex_index) vertex_index: u32,\n"
    "    @builtin(instance_index) instance_index: u32) -> CommandOut {\n"
    "  let command = commands[instance_index];\n"
    "  let uv = corner(vertex_index);\n"
    "  let point = command.rect.xy + uv * command.rect.zw;\n"
    "  let clip = vec2f(\n"
    "    point.x / command.viewport.x * 2.0 - 1.0,\n"
    "    1.0 - point.y / command.viewport.y * 2.0);\n"
    "  var output: CommandOut;\n"
    "  output.position = vec4f(clip, 0.0, 1.0);\n"
    "  output.uv = uv;\n"
    "  output.color = command.color;\n"
    "  output.size = command.rect.zw;\n"
    "  output.meta0 = command.meta0;\n"
    "  output.meta1 = command.meta1;\n"
    "  output.meta2 = command.meta2;\n"
    "  return output;\n"
    "}\n"
    "@fragment fn fs_command(input: CommandOut) -> @location(0) vec4f {\n"
    "  if (input.meta0.x < 0.5) {\n"
    "    let radius = min(input.meta0.y, min(input.size.x, input.size.y) * 0.5);\n"
    "    if (radius > 0.0) {\n"
    "      let pixel = input.uv * input.size;\n"
    "      let edge = min(pixel, input.size - pixel);\n"
    "      if (edge.x < radius && edge.y < radius &&\n"
    "          distance(edge, vec2f(radius, radius)) > radius) { discard; }\n"
    "    }\n"
    "  } else {\n"
    "    let column = min(u32(floor(input.uv.x * 5.0)), 4u);\n"
    "    let row = min(u32(floor(input.uv.y * 7.0)), 6u);\n"
    "    var bits = input.meta0.z;\n"
    "    if (row == 1u) { bits = input.meta0.w; }\n"
    "    if (row == 2u) { bits = input.meta1.x; }\n"
    "    if (row == 3u) { bits = input.meta1.y; }\n"
    "    if (row == 4u) { bits = input.meta1.z; }\n"
    "    if (row == 5u) { bits = input.meta1.w; }\n"
    "    if (row == 6u) { bits = input.meta2.x; }\n"
    "    if (((u32(bits + 0.5) >> column) & 1u) == 0u) { discard; }\n"
    "  }\n"
    "  return input.color;\n"
    "}\n"
    "struct ImagePlacement { rect: vec4f, viewport: vec4f }\n"
    /* Keep image bindings distinct from the command pipeline's binding 0.
     * A WGSL module cannot declare two globals at the same group/binding even
     * when separate entry points use them. Auto-layout still exposes only the
     * bindings reachable from each pipeline entry point. */
    "@group(0) @binding(1) var<storage, read> image_placements: array<ImagePlacement>;\n"
    "@group(0) @binding(2) var image_texture: texture_2d<f32>;\n"
    "@group(0) @binding(3) var image_sampler: sampler;\n"
    "struct ImageOut {\n"
    "  @builtin(position) position: vec4f,\n"
    "  @location(0) uv: vec2f,\n"
    "}\n"
    "@vertex fn vs_image(\n"
    "    @builtin(vertex_index) vertex_index: u32,\n"
    "    @builtin(instance_index) instance_index: u32) -> ImageOut {\n"
    "  let image_uniform = image_placements[instance_index];\n"
    "  let uv = corner(vertex_index);\n"
    "  let point = image_uniform.rect.xy + uv * image_uniform.rect.zw;\n"
    "  let clip = vec2f(\n"
    "    point.x / image_uniform.viewport.x * 2.0 - 1.0,\n"
    "    1.0 - point.y / image_uniform.viewport.y * 2.0);\n"
    "  var output: ImageOut;\n"
    "  output.position = vec4f(clip, 0.0, 1.0);\n"
    "  output.uv = uv;\n"
    "  return output;\n"
    "}\n"
    "@fragment fn fs_image(input: ImageOut) -> @location(0) vec4f {\n"
    "  return textureSample(image_texture, image_sampler, input.uv);\n"
    "}\n";

static WGPUShaderModule create_shader(WGPUDevice device) {
    WGPUShaderSourceWGSL wgsl = {
        .chain = { .sType = WGPUSType_ShaderSourceWGSL },
        .code = {
            .data = native_ui_wgsl,
            .length = strlen(native_ui_wgsl),
        },
    };
    WGPUShaderModuleDescriptor descriptor = {
        .nextInChain = (const WGPUChainedStruct*)&wgsl,
    };
    return wgpuDeviceCreateShaderModule(device, &descriptor);
}

static WGPURenderPipeline create_pipeline(
        WGPUDevice device,
        WGPUShaderModule shader,
        WGPUTextureFormat format,
        const char* vertex_entry,
        const char* fragment_entry) {
    WGPUBlendState blend = {
        .color = {
            .operation = WGPUBlendOperation_Add,
            .srcFactor = WGPUBlendFactor_SrcAlpha,
            .dstFactor = WGPUBlendFactor_OneMinusSrcAlpha,
        },
        .alpha = {
            .operation = WGPUBlendOperation_Add,
            .srcFactor = WGPUBlendFactor_One,
            .dstFactor = WGPUBlendFactor_OneMinusSrcAlpha,
        },
    };
    WGPUColorTargetState target = {
        .format = format,
        .blend = &blend,
        .writeMask = WGPUColorWriteMask_All,
    };
    WGPUFragmentState fragment = {
        .module = shader,
        .entryPoint = {
            .data = fragment_entry,
            .length = strlen(fragment_entry),
        },
        .targetCount = 1,
        .targets = &target,
    };
    WGPURenderPipelineDescriptor descriptor = {
        .vertex = {
            .module = shader,
            .entryPoint = {
                .data = vertex_entry,
                .length = strlen(vertex_entry),
            },
        },
        .fragment = &fragment,
        .primitive = { .topology = WGPUPrimitiveTopology_TriangleList },
        .multisample = { .count = 1, .mask = UINT32_MAX },
    };
    return wgpuDeviceCreateRenderPipeline(device, &descriptor);
}
#endif

static void release_image(BtrcNativeUiImage* image) {
    if (!image) { return; }
#ifndef BTRC_GPU_NATIVE_UI_CACHE_TEST
    if (image->bind_group) { wgpuBindGroupRelease(image->bind_group); }
    if (image->view) { wgpuTextureViewRelease(image->view); }
    if (image->texture) { wgpuTextureRelease(image->texture); }
#endif
    free(image->identity);
    memset(image, 0, sizeof(*image));
}

void btrc_gpu_native_ui_destroy(void* compositor) {
    BtrcNativeUi* ui = (BtrcNativeUi*)compositor;
    if (!ui) { return; }
    for (int index = 0; index < ui->image_count; ++index) {
        release_image(&ui->images[index]);
    }
#ifndef BTRC_GPU_NATIVE_UI_CACHE_TEST
    if (ui->image_sampler) { wgpuSamplerRelease(ui->image_sampler); }
    if (ui->command_bind_group) {
        wgpuBindGroupRelease(ui->command_bind_group);
    }
    if (ui->placement_buffer) { wgpuBufferRelease(ui->placement_buffer); }
    if (ui->command_buffer) { wgpuBufferRelease(ui->command_buffer); }
    if (ui->image_pipeline) {
        wgpuRenderPipelineRelease(ui->image_pipeline);
    }
    if (ui->command_pipeline) {
        wgpuRenderPipelineRelease(ui->command_pipeline);
    }
#endif
    free(ui->images);
    free(ui->order);
    free(ui->placements);
    free(ui->commands);
    free(ui);
}

void* btrc_gpu_native_ui_create(
        WGPUDevice device,
        WGPUQueue queue,
        WGPUTextureFormat surface_format) {
    if (!device || !queue || surface_format == WGPUTextureFormat_Undefined) {
        return NULL;
    }
    BtrcNativeUi* ui = (BtrcNativeUi*)calloc(1, sizeof(BtrcNativeUi));
    if (!ui) { return NULL; }
    ui->device = device;
    ui->queue = queue;
    ui->commands = (BtrcNativeUiCommand*)calloc(
        UI_MAX_COMMANDS, sizeof(BtrcNativeUiCommand));
    ui->placements = (BtrcNativeUiImagePlacement*)calloc(
        UI_MAX_ORDER, sizeof(BtrcNativeUiImagePlacement));
    ui->order = (BtrcNativeUiOrder*)calloc(
        UI_MAX_ORDER, sizeof(BtrcNativeUiOrder));
    ui->images = (BtrcNativeUiImage*)calloc(
        UI_MAX_IMAGES, sizeof(BtrcNativeUiImage));
    if (!ui->commands || !ui->placements || !ui->order || !ui->images) {
        btrc_gpu_native_ui_destroy(ui);
        return NULL;
    }

#ifdef BTRC_GPU_NATIVE_UI_CACHE_TEST
    native_ui_test_fail_create = false;
    native_ui_test_fail_upload = false;
    native_ui_test_uploads = 0;
    return ui;
#else
    WGPUShaderModule shader = create_shader(device);
    if (!shader) {
        btrc_gpu_native_ui_destroy(ui);
        return NULL;
    }
    ui->command_pipeline = create_pipeline(
        device, shader, surface_format, "vs_command", "fs_command");
    ui->image_pipeline = create_pipeline(
        device, shader, surface_format, "vs_image", "fs_image");
    wgpuShaderModuleRelease(shader);
    if (!ui->command_pipeline || !ui->image_pipeline) {
        btrc_gpu_native_ui_destroy(ui);
        return NULL;
    }

    WGPUBufferDescriptor command_descriptor = {
        .size = (uint64_t)UI_MAX_COMMANDS
            * (uint64_t)sizeof(BtrcNativeUiCommand),
        .usage = WGPUBufferUsage_Storage | WGPUBufferUsage_CopyDst,
        .mappedAtCreation = false,
    };
    ui->command_buffer = wgpuDeviceCreateBuffer(device, &command_descriptor);
    if (!ui->command_buffer) {
        btrc_gpu_native_ui_destroy(ui);
        return NULL;
    }
    WGPUBufferDescriptor placement_descriptor = {
        .size = (uint64_t)UI_MAX_ORDER
            * (uint64_t)sizeof(BtrcNativeUiImagePlacement),
        .usage = WGPUBufferUsage_Storage | WGPUBufferUsage_CopyDst,
        .mappedAtCreation = false,
    };
    ui->placement_buffer = wgpuDeviceCreateBuffer(
        device, &placement_descriptor);
    if (!ui->placement_buffer) {
        btrc_gpu_native_ui_destroy(ui);
        return NULL;
    }
    WGPUBindGroupLayout command_layout =
        wgpuRenderPipelineGetBindGroupLayout(ui->command_pipeline, 0);
    if (!command_layout) {
        btrc_gpu_native_ui_destroy(ui);
        return NULL;
    }
    WGPUBindGroupEntry command_entry = {
        .binding = 0,
        .buffer = ui->command_buffer,
        .size = command_descriptor.size,
    };
    WGPUBindGroupDescriptor command_group_descriptor = {
        .layout = command_layout,
        .entryCount = 1,
        .entries = &command_entry,
    };
    ui->command_bind_group = wgpuDeviceCreateBindGroup(
        device, &command_group_descriptor);
    wgpuBindGroupLayoutRelease(command_layout);
    if (!ui->command_bind_group) {
        btrc_gpu_native_ui_destroy(ui);
        return NULL;
    }

    WGPUSamplerDescriptor sampler_descriptor = {
        .addressModeU = WGPUAddressMode_ClampToEdge,
        .addressModeV = WGPUAddressMode_ClampToEdge,
        .addressModeW = WGPUAddressMode_ClampToEdge,
        .magFilter = WGPUFilterMode_Linear,
        .minFilter = WGPUFilterMode_Linear,
        .mipmapFilter = WGPUMipmapFilterMode_Nearest,
        .lodMinClamp = 0.0f,
        .lodMaxClamp = 1.0f,
        .compare = WGPUCompareFunction_Undefined,
        .maxAnisotropy = 1,
    };
    ui->image_sampler = wgpuDeviceCreateSampler(device, &sampler_descriptor);
    if (!ui->image_sampler) {
        btrc_gpu_native_ui_destroy(ui);
        return NULL;
    }
    return ui;
#endif
}

bool btrc_gpu_native_ui_begin(
        void* compositor, int logical_width, int logical_height) {
    BtrcNativeUi* ui = (BtrcNativeUi*)compositor;
    if (!ui || logical_width <= 0 || logical_height <= 0 ||
        logical_width > 4096 || logical_height > 4096) {
        return false;
    }
    ui->logical_width = logical_width;
    ui->logical_height = logical_height;
    ui->command_count = 0;
    ui->order_count = 0;
    ui->placement_count = 0;
    ui->frame_image_pixels = 0;
    ui->generation++;
    if (ui->generation == 0) { ui->generation = 1; }
    return true;
}

static bool append_command(
        BtrcNativeUi* ui, const BtrcNativeUiCommand* command) {
    if (!ui || !command || ui->logical_width <= 0 ||
        ui->logical_height <= 0 ||
        ui->command_count >= UI_MAX_COMMANDS ||
        ui->order_count >= UI_MAX_ORDER) {
        return false;
    }
    int index = ui->command_count++;
    ui->commands[index] = *command;
    ui->order[ui->order_count++] = (BtrcNativeUiOrder){
        .kind = 0,
        .index = (uint32_t)index,
    };
    return true;
}

static void initialize_command(
        BtrcNativeUi* ui,
        BtrcNativeUiCommand* command,
        float x,
        float y,
        float width,
        float height,
        float red,
        float green,
        float blue,
        float alpha) {
    memset(command, 0, sizeof(*command));
    command->rect[0] = x;
    command->rect[1] = y;
    command->rect[2] = width;
    command->rect[3] = height;
    command->color[0] = red;
    command->color[1] = green;
    command->color[2] = blue;
    command->color[3] = alpha;
    command->viewport[0] = (float)ui->logical_width;
    command->viewport[1] = (float)ui->logical_height;
}

bool btrc_gpu_native_ui_add_rect(
        void* compositor,
        float x,
        float y,
        float width,
        float height,
        float red,
        float green,
        float blue,
        float alpha,
        float radius) {
    BtrcNativeUi* ui = (BtrcNativeUi*)compositor;
    if (!ui || width <= 0.0f || height <= 0.0f ||
        radius < 0.0f) {
        return false;
    }
    BtrcNativeUiCommand command;
    initialize_command(ui, &command, x, y, width, height,
                       red, green, blue, alpha);
    command.meta0[0] = 0.0f;
    command.meta0[1] = radius;
    return append_command(ui, &command);
}

bool btrc_gpu_native_ui_add_glyph(
        void* compositor,
        float x,
        float y,
        float width,
        float height,
        float red,
        float green,
        float blue,
        float alpha,
        uint64_t glyph_bits) {
    BtrcNativeUi* ui = (BtrcNativeUi*)compositor;
    if (!ui || width <= 0.0f || height <= 0.0f) { return false; }
    BtrcNativeUiCommand command;
    initialize_command(ui, &command, x, y, width, height,
                       red, green, blue, alpha);
    command.meta0[0] = 1.0f;
    command.meta0[2] = (float)((glyph_bits >> 0) & UINT64_C(31));
    command.meta0[3] = (float)((glyph_bits >> 5) & UINT64_C(31));
    command.meta1[0] = (float)((glyph_bits >> 10) & UINT64_C(31));
    command.meta1[1] = (float)((glyph_bits >> 15) & UINT64_C(31));
    command.meta1[2] = (float)((glyph_bits >> 20) & UINT64_C(31));
    command.meta1[3] = (float)((glyph_bits >> 25) & UINT64_C(31));
    command.meta2[0] = (float)((glyph_bits >> 30) & UINT64_C(31));
    return append_command(ui, &command);
}

static int find_image(BtrcNativeUi* ui, const char* identity) {
    for (int index = 0; index < ui->image_count; ++index) {
        if (ui->images[index].identity &&
            strcmp(ui->images[index].identity, identity) == 0) {
            return index;
        }
    }
    return -1;
}

static int eviction_candidate(
        BtrcNativeUi* ui, const char* excluded_identity) {
    int candidate = -1;
    uint64_t oldest = UINT64_MAX;
    for (int index = 0; index < ui->image_count; ++index) {
        BtrcNativeUiImage* image = &ui->images[index];
        bool excluded = excluded_identity && image->identity &&
            strcmp(image->identity, excluded_identity) == 0;
        if (!excluded && image->last_used_generation != ui->generation &&
            image->last_used_generation < oldest) {
            candidate = index;
            oldest = image->last_used_generation;
        }
    }
    return candidate;
}

static void evict_image(BtrcNativeUi* ui, int index) {
    if (!ui || index < 0 || index >= ui->image_count) { return; }
    BtrcNativeUiImage* image = &ui->images[index];
    uint64_t pixels = (uint64_t)(unsigned int)image->width
        * (uint64_t)(unsigned int)image->height;
    if (ui->cached_image_pixels >= pixels) {
        ui->cached_image_pixels -= pixels;
    }
    release_image(image);
    int last = ui->image_count - 1;
    if (index != last) {
        ui->images[index] = ui->images[last];
        memset(&ui->images[last], 0, sizeof(ui->images[last]));
        /* Display-list entries use dense cache indices. If compaction moves a
         * texture already placed in this frame, preserve those placements. */
        for (int order_index = 0;
             order_index < ui->order_count;
             ++order_index) {
            BtrcNativeUiOrder* entry = &ui->order[order_index];
            if (entry->kind == 1 && entry->index == (uint32_t)last) {
                entry->index = (uint32_t)index;
            }
        }
    }
    ui->image_count--;
}

static bool image_room_possible(
        BtrcNativeUi* ui,
        uint64_t base_pixels,
        int base_count,
        uint64_t added_pixels,
        int added_count,
        const char* excluded_identity) {
    uint64_t evictable_pixels = 0;
    int evictable_count = 0;
    for (int index = 0; index < ui->image_count; ++index) {
        BtrcNativeUiImage* image = &ui->images[index];
        bool excluded = excluded_identity && image->identity &&
            strcmp(image->identity, excluded_identity) == 0;
        if (!excluded && image->last_used_generation != ui->generation) {
            evictable_pixels += (uint64_t)(unsigned int)image->width
                * (uint64_t)(unsigned int)image->height;
            evictable_count++;
        }
    }
    uint64_t minimum_pixels = base_pixels > evictable_pixels
        ? base_pixels - evictable_pixels : 0;
    int minimum_count = base_count - evictable_count;
    return added_pixels <= UI_MAX_IMAGE_PIXELS - minimum_pixels &&
        minimum_count + added_count <= UI_MAX_IMAGES;
}

static bool create_image_resources(
        BtrcNativeUi* ui,
        BtrcNativeUiImage* image,
        int width,
        int height) {
#ifdef BTRC_GPU_NATIVE_UI_CACHE_TEST
    (void)ui;
    if (native_ui_test_fail_create) {
        native_ui_test_fail_create = false;
        return false;
    }
    image->width = width;
    image->height = height;
    return true;
#else
    WGPUTextureDescriptor texture_descriptor = {
        .usage = WGPUTextureUsage_TextureBinding | WGPUTextureUsage_CopyDst,
        .dimension = WGPUTextureDimension_2D,
        .size = {
            .width = (uint32_t)width,
            .height = (uint32_t)height,
            .depthOrArrayLayers = 1,
        },
        .format = WGPUTextureFormat_RGBA8Unorm,
        .mipLevelCount = 1,
        .sampleCount = 1,
    };
    image->texture = wgpuDeviceCreateTexture(
        ui->device, &texture_descriptor);
    if (!image->texture) { return false; }
    image->view = wgpuTextureCreateView(image->texture, NULL);
    if (!image->view) { return false; }
    WGPUBindGroupLayout layout =
        wgpuRenderPipelineGetBindGroupLayout(ui->image_pipeline, 0);
    if (!layout) { return false; }
    WGPUBindGroupEntry entries[3] = {
        {
            .binding = 1,
            .buffer = ui->placement_buffer,
            .size = (uint64_t)UI_MAX_ORDER
                * (uint64_t)sizeof(BtrcNativeUiImagePlacement),
        },
        { .binding = 2, .textureView = image->view },
        { .binding = 3, .sampler = ui->image_sampler },
    };
    WGPUBindGroupDescriptor group_descriptor = {
        .layout = layout,
        .entryCount = 3,
        .entries = entries,
    };
    image->bind_group = wgpuDeviceCreateBindGroup(
        ui->device, &group_descriptor);
    wgpuBindGroupLayoutRelease(layout);
    if (!image->bind_group) { return false; }
    image->width = width;
    image->height = height;
    return true;
#endif
}

static bool upload_image(
        BtrcNativeUi* ui,
        BtrcNativeUiImage* image,
        const unsigned char* rgba) {
#ifdef BTRC_GPU_NATIVE_UI_CACHE_TEST
    (void)ui;
    (void)image;
    (void)rgba;
    if (native_ui_test_fail_upload) {
        native_ui_test_fail_upload = false;
        return false;
    }
    native_ui_test_uploads++;
    return true;
#else
    size_t row_bytes = (size_t)image->width * 4u;
    size_t padded_row_bytes = (row_bytes + 255u) & ~(size_t)255u;
    if (padded_row_bytes > UINT32_MAX ||
        (size_t)image->height > SIZE_MAX / padded_row_bytes) {
        return false;
    }
    size_t upload_bytes = padded_row_bytes * (size_t)image->height;
    unsigned char* upload = (unsigned char*)malloc(upload_bytes);
    if (!upload) { return false; }
    for (int row = 0; row < image->height; ++row) {
        unsigned char* target = upload + (size_t)row * padded_row_bytes;
        memcpy(target, rgba + (size_t)row * row_bytes, row_bytes);
        if (padded_row_bytes > row_bytes) {
            memset(target + row_bytes, 0, padded_row_bytes - row_bytes);
        }
    }
    WGPUTexelCopyTextureInfo destination = {
        .texture = image->texture,
        .aspect = WGPUTextureAspect_All,
    };
    WGPUTexelCopyBufferLayout layout = {
        .bytesPerRow = (uint32_t)padded_row_bytes,
        .rowsPerImage = (uint32_t)image->height,
    };
    WGPUExtent3D extent = {
        .width = (uint32_t)image->width,
        .height = (uint32_t)image->height,
        .depthOrArrayLayers = 1,
    };
    wgpuQueueWriteTexture(
        ui->queue, &destination, upload, upload_bytes, &layout, &extent);
    free(upload);
    return true;
#endif
}

bool btrc_gpu_native_ui_add_image(
        void* compositor,
        const char* identity,
        const unsigned char* rgba,
        int source_width,
        int source_height,
        uint64_t source_revision,
        float x,
        float y,
        float width,
        float height) {
    BtrcNativeUi* ui = (BtrcNativeUi*)compositor;
    if (!ui || !identity || identity[0] == '\0' || !rgba ||
        source_width <= 0 || source_height <= 0 ||
        source_width > UI_MAX_IMAGE_DIMENSION ||
        source_height > UI_MAX_IMAGE_DIMENSION ||
        width <= 0.0f || height <= 0.0f ||
        strlen(identity) > 512u || ui->order_count >= UI_MAX_ORDER ||
        ui->placement_count >= UI_MAX_ORDER) {
        return false;
    }
    uint64_t pixels = (uint64_t)(unsigned int)source_width
        * (uint64_t)(unsigned int)source_height;
    if (pixels > UINT64_C(16777216) ||
        ui->frame_image_pixels > UI_MAX_IMAGE_PIXELS - pixels) {
        return false;
    }
    int index = find_image(ui, identity);
    BtrcNativeUiImage* image = index >= 0 ? &ui->images[index] : NULL;
    bool dimensions_changed = image &&
        (image->width != source_width || image->height != source_height);
    bool content_changed = !image || dimensions_changed ||
        image->source_identity != rgba ||
        image->source_revision != source_revision;

    if (!image || dimensions_changed) {
        BtrcNativeUiImage candidate;
        memset(&candidate, 0, sizeof(candidate));
        size_t identity_bytes = strlen(identity) + 1u;
        candidate.identity = (char*)malloc(identity_bytes);
        if (!candidate.identity) { return false; }
        memcpy(candidate.identity, identity, identity_bytes);
        if (!create_image_resources(
                ui, &candidate, source_width, source_height) ||
            !upload_image(ui, &candidate, rgba)) {
            release_image(&candidate);
            return false;
        }
        candidate.source_identity = rgba;
        candidate.source_revision = source_revision;
        candidate.last_used_generation = ui->generation;

        uint64_t previous_pixels = image
            ? (uint64_t)(unsigned int)image->width
                * (uint64_t)(unsigned int)image->height
            : 0;
        uint64_t base_pixels = ui->cached_image_pixels - previous_pixels;
        int base_count = ui->image_count - (image ? 1 : 0);
        if (!image_room_possible(
                ui, base_pixels, base_count, pixels, 1, identity)) {
            release_image(&candidate);
            return false;
        }

        while (base_pixels > UI_MAX_IMAGE_PIXELS - pixels ||
               base_count + 1 > UI_MAX_IMAGES) {
            int evicted = eviction_candidate(ui, identity);
            if (evicted < 0) {
                release_image(&candidate);
                return false;
            }
            uint64_t evicted_pixels =
                (uint64_t)(unsigned int)ui->images[evicted].width
                * (uint64_t)(unsigned int)ui->images[evicted].height;
            evict_image(ui, evicted);
            base_pixels -= evicted_pixels;
            base_count--;
        }

        if (image) {
            index = find_image(ui, identity);
            if (index < 0) {
                release_image(&candidate);
                return false;
            }
            BtrcNativeUiImage* previous = &ui->images[index];
            uint64_t current_previous_pixels =
                (uint64_t)(unsigned int)previous->width
                * (uint64_t)(unsigned int)previous->height;
            if (ui->cached_image_pixels >= current_previous_pixels) {
                ui->cached_image_pixels -= current_previous_pixels;
            }
            release_image(previous);
            *previous = candidate;
            image = previous;
        } else {
            index = ui->image_count++;
            ui->images[index] = candidate;
            image = &ui->images[index];
        }
        ui->cached_image_pixels += pixels;
    } else if (content_changed) {
        if (!upload_image(ui, image, rgba)) { return false; }
        image->source_identity = rgba;
        image->source_revision = source_revision;
    }

    int placement = ui->placement_count++;
    BtrcNativeUiImagePlacement* placed = &ui->placements[placement];
    placed->rect[0] = x;
    placed->rect[1] = y;
    placed->rect[2] = width;
    placed->rect[3] = height;
    placed->viewport[0] = (float)ui->logical_width;
    placed->viewport[1] = (float)ui->logical_height;
    placed->viewport[2] = 0.0f;
    placed->viewport[3] = 0.0f;
    image->last_used_generation = ui->generation;
    ui->frame_image_pixels += pixels;
    ui->order[ui->order_count++] = (BtrcNativeUiOrder){
        .kind = 1,
        .index = (uint32_t)index,
        .placement = (uint32_t)placement,
    };
    return true;
}

bool btrc_gpu_native_ui_draw(
        void* compositor, WGPURenderPassEncoder active_pass) {
    BtrcNativeUi* ui = (BtrcNativeUi*)compositor;
    if (!ui || !active_pass || ui->logical_width <= 0 ||
        ui->logical_height <= 0) {
        return false;
    }
#ifdef BTRC_GPU_NATIVE_UI_CACHE_TEST
    for (int index = 0; index < ui->order_count; ++index) {
        BtrcNativeUiOrder entry = ui->order[index];
        if (entry.kind == 1 &&
            (entry.index >= (uint32_t)ui->image_count ||
             entry.placement >= (uint32_t)ui->placement_count)) {
            return false;
        }
    }
    return true;
#else
    if (ui->command_count > 0) {
        size_t bytes = (size_t)ui->command_count
            * sizeof(BtrcNativeUiCommand);
        wgpuQueueWriteBuffer(
            ui->queue, ui->command_buffer, 0, ui->commands, bytes);
    }
    if (ui->placement_count > 0) {
        size_t bytes = (size_t)ui->placement_count
            * sizeof(BtrcNativeUiImagePlacement);
        wgpuQueueWriteBuffer(
            ui->queue, ui->placement_buffer, 0, ui->placements, bytes);
    }
    int cursor = 0;
    while (cursor < ui->order_count) {
        BtrcNativeUiOrder entry = ui->order[cursor];
        if (entry.kind == 0) {
            uint32_t first = entry.index;
            uint32_t count = 1;
            while (cursor + (int)count < ui->order_count) {
                BtrcNativeUiOrder next = ui->order[cursor + (int)count];
                if (next.kind != 0 || next.index != first + count) { break; }
                count++;
            }
            wgpuRenderPassEncoderSetPipeline(
                active_pass, ui->command_pipeline);
            wgpuRenderPassEncoderSetBindGroup(
                active_pass, 0, ui->command_bind_group, 0, NULL);
            wgpuRenderPassEncoderDraw(active_pass, 6, count, 0, first);
            cursor += (int)count;
        } else {
            if (entry.index >= (uint32_t)ui->image_count ||
                !ui->images[entry.index].bind_group) {
                return false;
            }
            wgpuRenderPassEncoderSetPipeline(
                active_pass, ui->image_pipeline);
            wgpuRenderPassEncoderSetBindGroup(
                active_pass, 0, ui->images[entry.index].bind_group, 0, NULL);
            wgpuRenderPassEncoderDraw(
                active_pass, 6, 1, 0, entry.placement);
            cursor++;
        }
    }
    return true;
#endif
}

int btrc_gpu_native_ui_command_count(void* compositor) {
    BtrcNativeUi* ui = (BtrcNativeUi*)compositor;
    return ui ? ui->command_count : 0;
}

int btrc_gpu_native_ui_image_count(void* compositor) {
    BtrcNativeUi* ui = (BtrcNativeUi*)compositor;
    return ui ? ui->image_count : 0;
}

#ifdef BTRC_GPU_NATIVE_UI_CACHE_TEST
void btrc_gpu_native_ui_test_fail_next_create(void) {
    native_ui_test_fail_create = true;
}

void btrc_gpu_native_ui_test_fail_next_upload(void) {
    native_ui_test_fail_upload = true;
}

int btrc_gpu_native_ui_test_upload_count(void) {
    return native_ui_test_uploads;
}

int btrc_gpu_native_ui_test_placement_count(void* compositor) {
    BtrcNativeUi* ui = (BtrcNativeUi*)compositor;
    return ui ? ui->placement_count : 0;
}

uint64_t btrc_gpu_native_ui_test_cached_pixels(void* compositor) {
    BtrcNativeUi* ui = (BtrcNativeUi*)compositor;
    return ui ? ui->cached_image_pixels : 0;
}

bool btrc_gpu_native_ui_test_has_image(
        void* compositor, const char* identity) {
    BtrcNativeUi* ui = (BtrcNativeUi*)compositor;
    return ui && identity && find_image(ui, identity) >= 0;
}
#endif
