/* POST via APK libcurl 7.56.1 + OpenSSL 1.1.0f. No tokens in output. */
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CURLOPTTYPE_LONG 0
#define CURLOPTTYPE_OBJECTPOINT 10000
#define CURLOPTTYPE_FUNCTIONPOINT 20000
#define CURLOPT_WRITEDATA (CURLOPTTYPE_OBJECTPOINT + 1)
#define CURLOPT_URL (CURLOPTTYPE_OBJECTPOINT + 2)
#define CURLOPT_ERRORBUFFER (CURLOPTTYPE_OBJECTPOINT + 10)
#define CURLOPT_WRITEFUNCTION (CURLOPTTYPE_FUNCTIONPOINT + 11)
#define CURLOPT_TIMEOUT (CURLOPTTYPE_LONG + 13)
#define CURLOPT_POSTFIELDS (CURLOPTTYPE_OBJECTPOINT + 15)
#define CURLOPT_USERAGENT (CURLOPTTYPE_OBJECTPOINT + 18)
#define CURLOPT_HTTPHEADER (CURLOPTTYPE_OBJECTPOINT + 23)
#define CURLOPT_POST (CURLOPTTYPE_LONG + 47)
#define CURLOPT_POSTFIELDSIZE (CURLOPTTYPE_LONG + 60)
#define CURLOPT_SSL_VERIFYPEER (CURLOPTTYPE_LONG + 64)
#define CURLOPT_CAINFO (CURLOPTTYPE_OBJECTPOINT + 65)
#define CURLOPT_SSL_VERIFYHOST (CURLOPTTYPE_LONG + 81)
#define CURLOPT_COOKIEFILE (CURLOPTTYPE_OBJECTPOINT + 31)
#define CURLOPT_COOKIEJAR (CURLOPTTYPE_OBJECTPOINT + 82)
#define CURLOPT_HTTP_VERSION (CURLOPTTYPE_LONG + 84)
#define CURLOPT_CAPATH (CURLOPTTYPE_OBJECTPOINT + 97)
#define CURLOPT_NOSIGNAL (CURLOPTTYPE_LONG + 99)
#define CURL_HTTP_VERSION_1_1 2
#define CURL_HTTP_VERSION_2_0 3
#define CURLINFO_LONG 0x200000
#define CURLINFO_RESPONSE_CODE (CURLINFO_LONG + 2)
#define CURLINFO_HTTP_VERSION (CURLINFO_LONG + 46)
#define CURL_GLOBAL_DEFAULT 3
#define CURL_ERROR_SIZE 256

typedef void CURL;
typedef struct curl_slist curl_slist;
typedef int (*setopt_fn)(CURL *, int, ...);
typedef int (*getinfo_fn)(CURL *, int, ...);
typedef CURL *(*init_fn)(void);
typedef int (*perform_fn)(CURL *);
typedef void (*cleanup_fn)(CURL *);
typedef int (*global_init_fn)(long);
typedef void (*global_cleanup_fn)(void);
typedef const char *(*version_fn)(void);
typedef const char *(*strerror_fn)(int);
typedef curl_slist *(*slist_append_fn)(curl_slist *, const char *);
typedef void (*slist_free_fn)(curl_slist *);

struct buf {
    char *data;
    size_t len;
};

static size_t write_cb(char *ptr, size_t size, size_t nmemb, void *userdata) {
    size_t n = size * nmemb;
    struct buf *b = (struct buf *)userdata;
    char *p = (char *)realloc(b->data, b->len + n + 1);
    if (!p) {
        return 0;
    }
    b->data = p;
    memcpy(b->data + b->len, ptr, n);
    b->len += n;
    b->data[b->len] = 0;
    return n;
}

static char *read_file(const char *path, size_t *out_len) {
    FILE *f = fopen(path, "rb");
    if (!f) {
        return NULL;
    }
    if (fseek(f, 0, SEEK_END) != 0) {
        fclose(f);
        return NULL;
    }
    long sz = ftell(f);
    if (sz < 0) {
        fclose(f);
        return NULL;
    }
    rewind(f);
    char *buf = (char *)malloc((size_t)sz + 1);
    if (!buf) {
        fclose(f);
        return NULL;
    }
    size_t n = fread(buf, 1, (size_t)sz, f);
    fclose(f);
    buf[n] = 0;
    if (out_len) {
        *out_len = n;
    }
    return buf;
}

static void cookie_path_from_url_file(const char *url_path, char *out, size_t n) {
    size_t i;
    size_t slash = 0;
    if (!url_path || !out || n < 16) {
        return;
    }
    for (i = 0; url_path[i]; ++i) {
        if (url_path[i] == '/' || url_path[i] == '\\') {
            slash = i;
        }
    }
    if (slash == 0 || slash + 1 + 11 >= n) {
        snprintf(out, n, "cookies.txt");
        return;
    }
    memcpy(out, url_path, slash + 1);
    memcpy(out + slash + 1, "cookies.txt", 12);
}

static int write_file(const char *path, const char *data, size_t len) {
    FILE *f = fopen(path, "wb");
    if (!f) {
        return -1;
    }
    size_t n = fwrite(data, 1, len, f);
    fclose(f);
    return n == len ? 0 : -1;
}

int main(int argc, char **argv) {
    if (argc != 5) {
        fprintf(stderr, "usage: oldcurl_post <url_file> <body_file> <out_file> <ua_file>\n");
        return 2;
    }
    char *url = read_file(argv[1], NULL);
    const char *body_path = argv[2];
    const char *out_path = argv[3];
    char *ua = read_file(argv[4], NULL);
    if (!url || !ua) {
        fprintf(stderr, "{\"ok\":false,\"error\":\"read-url-or-ua\"}\n");
        free(url);
        free(ua);
        return 3;
    }
    for (char *p = url; *p; ++p) {
        if (*p == '\n' || *p == '\r') {
            *p = 0;
            break;
        }
    }
    for (char *p = ua; *p; ++p) {
        if (*p == '\n' || *p == '\r') {
            *p = 0;
            break;
        }
    }

    size_t body_len = 0;
    char *body = read_file(body_path, &body_len);
    if (!body) {
        fprintf(stderr, "{\"ok\":false,\"error\":\"read-body\"}\n");
        free(url);
        free(ua);
        return 3;
    }

    void *h = dlopen("libcurl.so", RTLD_NOW);
    if (!h) {
        fprintf(stderr, "{\"ok\":false,\"error\":\"dlopen-libcurl\",\"dlerror\":\"%s\"}\n", dlerror());
        free(body);
        free(url);
        free(ua);
        return 4;
    }

    global_init_fn curl_global_init = (global_init_fn)dlsym(h, "curl_global_init");
    global_cleanup_fn curl_global_cleanup = (global_cleanup_fn)dlsym(h, "curl_global_cleanup");
    init_fn curl_easy_init = (init_fn)dlsym(h, "curl_easy_init");
    setopt_fn curl_easy_setopt = (setopt_fn)dlsym(h, "curl_easy_setopt");
    perform_fn curl_easy_perform = (perform_fn)dlsym(h, "curl_easy_perform");
    cleanup_fn curl_easy_cleanup = (cleanup_fn)dlsym(h, "curl_easy_cleanup");
    getinfo_fn curl_easy_getinfo = (getinfo_fn)dlsym(h, "curl_easy_getinfo");
    version_fn curl_version = (version_fn)dlsym(h, "curl_version");
    strerror_fn curl_easy_strerror = (strerror_fn)dlsym(h, "curl_easy_strerror");
    slist_append_fn curl_slist_append = (slist_append_fn)dlsym(h, "curl_slist_append");
    slist_free_fn curl_slist_free_all = (slist_free_fn)dlsym(h, "curl_slist_free_all");
    if (!curl_global_init || !curl_easy_init || !curl_easy_setopt || !curl_easy_perform) {
        fprintf(stderr, "{\"ok\":false,\"error\":\"dlsym\"}\n");
        free(body);
        return 5;
    }

    const char *ver = curl_version ? curl_version() : "";
    curl_global_init(CURL_GLOBAL_DEFAULT);
    CURL *easy = curl_easy_init();
    if (!easy) {
        fprintf(stderr, "{\"ok\":false,\"error\":\"easy-init\",\"curl_version\":\"%s\"}\n", ver);
        free(body);
        return 6;
    }

    struct buf out = {0};
    char errbuf[CURL_ERROR_SIZE];
    char cookie_path[512];
    errbuf[0] = 0;
    cookie_path[0] = 0;
    cookie_path_from_url_file(argv[1], cookie_path, sizeof(cookie_path));
    curl_slist *hdrs = NULL;
    hdrs = curl_slist_append(hdrs, "Content-Type: application/x-www-form-urlencoded");
    hdrs = curl_slist_append(hdrs, "charsets: utf-8");
    hdrs = curl_slist_append(hdrs, "Expect:");

    curl_easy_setopt(easy, CURLOPT_URL, url);
    if (cookie_path[0]) {
        FILE *cf = fopen(cookie_path, "ab");
        if (cf) {
            fclose(cf);
        }
        curl_easy_setopt(easy, CURLOPT_COOKIEFILE, cookie_path);
        curl_easy_setopt(easy, CURLOPT_COOKIEJAR, cookie_path);
    }
    curl_easy_setopt(easy, CURLOPT_POST, 1L);
    curl_easy_setopt(easy, CURLOPT_POSTFIELDS, body);
    curl_easy_setopt(easy, CURLOPT_POSTFIELDSIZE, (long)body_len);
    curl_easy_setopt(easy, CURLOPT_HTTPHEADER, hdrs);
    curl_easy_setopt(easy, CURLOPT_USERAGENT, ua);
    int httpver_setopt = curl_easy_setopt(easy, CURLOPT_HTTP_VERSION, (long)CURL_HTTP_VERSION_2_0);
    curl_easy_setopt(easy, CURLOPT_TIMEOUT, 30L);
    curl_easy_setopt(easy, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(easy, CURLOPT_WRITEFUNCTION, write_cb);
    curl_easy_setopt(easy, CURLOPT_WRITEDATA, &out);
    curl_easy_setopt(easy, CURLOPT_ERRORBUFFER, errbuf);
    curl_easy_setopt(easy, CURLOPT_CAPATH, "/apex/com.android.conscrypt/cacerts");
    curl_easy_setopt(easy, CURLOPT_SSL_VERIFYPEER, 1L);
    curl_easy_setopt(easy, CURLOPT_SSL_VERIFYHOST, 2L);

    int rc = curl_easy_perform(easy);
    int ssl_verify = 1;
    if (rc != 0) {
        curl_easy_setopt(easy, CURLOPT_SSL_VERIFYPEER, 0L);
        curl_easy_setopt(easy, CURLOPT_SSL_VERIFYHOST, 0L);
        ssl_verify = 0;
        errbuf[0] = 0;
        if (out.data) {
            free(out.data);
            out.data = NULL;
            out.len = 0;
        }
        rc = curl_easy_perform(easy);
    }

    long http_code = 0;
    long http_ver = 0;
    if (curl_easy_getinfo) {
        curl_easy_getinfo(easy, CURLINFO_RESPONSE_CODE, &http_code);
        curl_easy_getinfo(easy, CURLINFO_HTTP_VERSION, &http_ver);
    }

    int written = 0;
    if (out.data && out.len) {
        written = write_file(out_path, out.data, out.len) == 0;
    } else {
        written = write_file(out_path, "", 0) == 0;
    }

    const char *estr = (rc != 0 && curl_easy_strerror) ? curl_easy_strerror(rc) : "";
    for (char *p = errbuf; *p; ++p) {
        if (*p == '"' || *p == '\\' || *p == '\n' || *p == '\r') {
            *p = ' ';
        }
    }
    fprintf(stderr,
            "{\"ok\":%s,\"curl_version\":\"%s\",\"curl_code\":%d,\"curl_error\":\"%s\","
            "\"http_code\":%ld,\"http_version_setopt\":%d,\"http_version\":%ld,"
            "\"ssl_verify\":%d,\"body_bytes\":%zu,\"written\":%s,"
            "\"headers\":\"content-type,charsets,expect\"}\n",
            rc == 0 ? "true" : "false",
            ver,
            rc,
            errbuf[0] ? errbuf : estr,
            http_code,
            httpver_setopt,
            http_ver,
            ssl_verify,
            out.len,
            written ? "true" : "false");

    if (hdrs && curl_slist_free_all) {
        curl_slist_free_all(hdrs);
    }
    curl_easy_cleanup(easy);
    if (curl_global_cleanup) {
        curl_global_cleanup();
    }
    free(out.data);
    free(body);
    free(url);
    free(ua);
    return rc == 0 ? 0 : 7;
}
