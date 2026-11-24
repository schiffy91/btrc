#include "SharedFrame.h"
#include "DmaBufReceiver.h"
#include "GtkShimPrivate.h"

bool btrcGtkSupportsSharedFrames(void) {
    GdkDisplay* display = gdk_display_get_default();
    return display && gdk_dmabuf_formats_get_n_formats(gdk_display_get_dmabuf_formats(display)) > 0;
}

BtrcShimControl* btrcGtkSharedFrameCreate(unsigned int id) {
    GtkWidget* picture = gtk_picture_new();
    gtk_picture_set_content_fit(GTK_PICTURE(picture), GTK_CONTENT_FIT_CONTAIN);
    gtk_picture_set_can_shrink(GTK_PICTURE(picture), TRUE);
    gtk_widget_set_can_target(picture, FALSE);
    GtkWidget* offload = gtk_graphics_offload_new(picture);
    gtk_widget_set_can_target(offload, FALSE);
    return btrcGtkControlNew(id, offload);
}

static GtkPicture* framePicture(BtrcShimControl* control) {
    GtkWidget* offload = btrcGtkControlWidget(control);
    return GTK_PICTURE(gtk_graphics_offload_get_child(GTK_GRAPHICS_OFFLOAD(offload)));
}

void btrcGtkSharedFrameClear(BtrcShimControl* control) {
    gtk_picture_set_paintable(framePicture(control), NULL);
}

static void releaseBuffer(gpointer data) {
    BtrcDmaBufFrame* frame = data;
    btrcDmaBufRelease(frame);
    g_free(frame);
}

bool btrcGtkPictureReceive(BtrcShimControl* picture, BtrcDmaBufReceiver* receiver) {
    BtrcDmaBufFrame packet;
    if (!btrcDmaBufReceive(receiver, &packet)) { return false; }
    GtkWidget* widget = btrcGtkControlWidget(picture);
    GdkDisplay* display = gtk_widget_get_display(widget);
    BtrcDmaBufHeader* h = &packet.header;
    if (!gdk_dmabuf_formats_contains(gdk_display_get_dmabuf_formats(display), h->fourcc, h->modifier)) {
        btrcDmaBufRelease(&packet);
        return false;
    }

    GdkDmabufTextureBuilder* builder = gdk_dmabuf_texture_builder_new();
    gdk_dmabuf_texture_builder_set_display(builder, display);
    gdk_dmabuf_texture_builder_set_width(builder, h->width);
    gdk_dmabuf_texture_builder_set_height(builder, h->height);
    gdk_dmabuf_texture_builder_set_fourcc(builder, h->fourcc);
    gdk_dmabuf_texture_builder_set_modifier(builder, h->modifier);
    gdk_dmabuf_texture_builder_set_n_planes(builder, h->planes);
    for (uint32_t i = 0; i < h->planes; ++i) {
        gdk_dmabuf_texture_builder_set_fd(builder, i, packet.fd[i]);
        gdk_dmabuf_texture_builder_set_stride(builder, i, h->plane[i].stride);
        gdk_dmabuf_texture_builder_set_offset(builder, i, h->plane[i].offset);
    }
    /* GDK borrows the descriptors until the last texture reference goes away. */
    BtrcDmaBufFrame* owner = g_memdup2(&packet, sizeof packet);
    GdkTexture* texture = gdk_dmabuf_texture_builder_build(builder, releaseBuffer, owner, NULL);
    g_object_unref(builder);
    if (!texture) { releaseBuffer(owner); return false; }
    gtk_picture_set_paintable(framePicture(picture), GDK_PAINTABLE(texture));
    g_object_unref(texture);
    return true;
}

int btrcGtkPictureFrameWidth(BtrcShimControl* picture) {
    GdkPaintable* image = gtk_picture_get_paintable(framePicture(picture));
    return image ? gdk_paintable_get_intrinsic_width(image) : 0;
}

int btrcGtkPictureFrameHeight(BtrcShimControl* picture) {
    GdkPaintable* image = gtk_picture_get_paintable(framePicture(picture));
    return image ? gdk_paintable_get_intrinsic_height(image) : 0;
}
