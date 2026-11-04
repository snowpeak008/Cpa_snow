package main

/*
#include <stdint.h>
#include <stdlib.h>
typedef struct { void* ptr; size_t len; } buffer;
typedef struct { uint32_t abi_version; void* ctx; void* call; void* free_buffer; } host_api;
typedef int (*host_call_fn)(void*, const char*, const uint8_t*, size_t, buffer*);
typedef void (*host_free_fn)(void*, size_t);
static host_api saved_host;
static void save_host(const host_api* host) {
    if (host != NULL) saved_host = *host;
}
static int read_host_accounts(buffer* out) {
    if (saved_host.call == NULL || saved_host.free_buffer == NULL) return 1;
    return ((host_call_fn)saved_host.call)(saved_host.ctx, "host.auth.list", (const uint8_t*)"{}", 2, out);
}
static void release_host_buffer(buffer b) {
    if (b.ptr != NULL && saved_host.free_buffer != NULL) ((host_free_fn)saved_host.free_buffer)(b.ptr, b.len);
}
extern int pluginCall(char*, uint8_t*, size_t, buffer*);
extern void pluginFree(void*, size_t);
extern void pluginShutdown(void);
typedef struct { uint32_t abi_version; int (*call)(char*,uint8_t*,size_t,buffer*); void (*free_buffer)(void*,size_t); void (*shutdown)(void); } plugin_api;
static void init_api(plugin_api* p) { p->abi_version=1; p->call=pluginCall; p->free_buffer=pluginFree; p->shutdown=pluginShutdown; }
*/
import "C"

import (
	"encoding/json"
	"unsafe"
)

//export cliproxy_plugin_init
func cliproxy_plugin_init(host *C.host_api, p *C.plugin_api) C.int {
	if p == nil {
		return 1
	}
	C.save_host(host)
	C.init_api(p)
	return 0
}

// Reads only CPA's existing local account metadata; never credentials or quotas.
func readHostAccountState(authID string) accountState {
	var response C.buffer
	rc := C.read_host_accounts(&response)
	defer C.release_host_buffer(response)
	if rc != 0 || response.ptr == nil || response.len == 0 || response.len > 16*1024*1024 {
		return accountUnknown
	}
	return accountStateFromList(C.GoBytes(response.ptr, C.int(response.len)), authID)
}

//export pluginCall
func pluginCall(method *C.char, data *C.uint8_t, n C.size_t, out *C.buffer) C.int {
	if out == nil {
		return 1
	}
	out.ptr = nil
	out.len = 0
	result := handle(C.GoString(method), C.GoBytes(unsafe.Pointer(data), C.int(n)))
	b, err := json.Marshal(result)
	if err != nil {
		b = []byte(`{"ok":false,"error":{"code":"encode_error","message":"encoding failed"}}`)
	}
	out.ptr = C.CBytes(b)
	out.len = C.size_t(len(b))
	return 0
}

//export pluginFree
func pluginFree(p unsafe.Pointer, _ C.size_t) { C.free(p) }

//export pluginShutdown
func pluginShutdown() {}

func main() {}
