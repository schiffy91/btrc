int btrc_win_compat_helper(void);
int btrc_win_compat_windows_header(void);

int main(void) {
    return btrc_win_compat_helper()
        && btrc_win_compat_windows_header() ? 0 : 1;
}
