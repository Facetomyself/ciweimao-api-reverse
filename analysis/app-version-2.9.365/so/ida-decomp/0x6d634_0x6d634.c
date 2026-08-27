// 0x6d634 @ 0x6d634
void __fastcall CenterDataAPI::GetInfo(__int64 a1, __int64 a2, __int64 a3, __int64 a4)
{
  __int64 v7; // x24
  __int64 v8; // x0
  __int64 v9; // x25
  __int64 v10; // x0
  __int64 v11; // x26
  __int64 v12; // x0
  __int64 v13; // x21
  __int64 v14; // x24
  __int64 v15; // x0
  __int64 v16; // x0
  char *v17; // x0
  __int64 v18; // x0
  __int64 v19; // x0
  __int64 v20; // x21
  __int64 v21; // x0
  __int64 v22; // x0
  __int64 v23; // x0
  const char *v24; // x21
  size_t v25; // x0
  size_t v26; // x20
  char *v27; // x22
  unsigned __int64 v28; // x23
  __int128 v29; // q0
  __int64 v30; // x8
  char v31; // w9
  _QWORD v32[2]; // [xsp+0h] [xbp-240h] BYREF
  void *v33; // [xsp+10h] [xbp-230h]
  __int128 v34; // [xsp+18h] [xbp-228h] BYREF
  __int64 v35; // [xsp+28h] [xbp-218h]
  char v36[16]; // [xsp+30h] [xbp-210h] BYREF
  __int128 v37; // [xsp+40h] [xbp-200h]
  __int128 v38; // [xsp+50h] [xbp-1F0h]
  __int128 v39; // [xsp+60h] [xbp-1E0h]
  __int128 v40; // [xsp+70h] [xbp-1D0h]
  __int128 v41; // [xsp+80h] [xbp-1C0h]
  __int128 v42; // [xsp+90h] [xbp-1B0h]
  __int128 v43; // [xsp+A0h] [xbp-1A0h]
  char v44[16]; // [xsp+B0h] [xbp-190h] BYREF
  __int128 v45; // [xsp+C0h] [xbp-180h]
  __int128 v46; // [xsp+D0h] [xbp-170h]
  __int128 v47; // [xsp+E0h] [xbp-160h]
  __int128 v48; // [xsp+F0h] [xbp-150h]
  __int128 v49; // [xsp+100h] [xbp-140h]
  __int128 v50; // [xsp+110h] [xbp-130h]
  __int128 v51; // [xsp+120h] [xbp-120h]
  char v52[16]; // [xsp+130h] [xbp-110h] BYREF
  __int128 v53; // [xsp+140h] [xbp-100h]
  __int128 v54; // [xsp+150h] [xbp-F0h]
  __int128 v55; // [xsp+160h] [xbp-E0h]
  __int128 v56; // [xsp+170h] [xbp-D0h]
  __int128 v57; // [xsp+180h] [xbp-C0h]
  __int128 v58; // [xsp+190h] [xbp-B0h]
  __int128 v59; // [xsp+1A0h] [xbp-A0h]
  char s[16]; // [xsp+1B0h] [xbp-90h] BYREF
  __int128 v61; // [xsp+1C0h] [xbp-80h]
  __int128 v62; // [xsp+1D0h] [xbp-70h]
  __int128 v63; // [xsp+1E0h] [xbp-60h]
  __int128 v64; // [xsp+1F0h] [xbp-50h]
  __int128 v65; // [xsp+200h] [xbp-40h]
  __int128 v66; // [xsp+210h] [xbp-30h]
  __int128 v67; // [xsp+220h] [xbp-20h]
  __int64 v68; // [xsp+238h] [xbp-8h]

  v68 = *(_QWORD *)(_ReadStatusReg(TPIDR_EL0) + 40); /*0x6d684*/
  v66 = 0u; /*0x6d68c*/
  v67 = 0u; /*0x6d68c*/
  v64 = 0u; /*0x6d690*/
  v65 = 0u; /*0x6d690*/
  v62 = 0u; /*0x6d694*/
  v63 = 0u; /*0x6d694*/
  *(_OWORD *)s = 0u; /*0x6d698*/
  v61 = 0u; /*0x6d698*/
  __system_property_get("ro.build.version.sdk", s); /*0x6d69c*/
  if ( !s[0] ) /*0x6d6a4*/
    strcpy(s, "unknown"); /*0x6d6a8*/
  std::string::assign(a1 + 120, s); /*0x6d6b4*/
  v58 = 0u; /*0x6d6c8*/
  v59 = 0u; /*0x6d6c8*/
  v56 = 0u; /*0x6d6cc*/
  v57 = 0u; /*0x6d6cc*/
  v54 = 0u; /*0x6d6d0*/
  v55 = 0u; /*0x6d6d0*/
  *(_OWORD *)v52 = 0u; /*0x6d6d4*/
  v53 = 0u; /*0x6d6d4*/
  __system_property_get("ro.product.model", v52); /*0x6d6d8*/
  if ( !v52[0] ) /*0x6d6e0*/
    strcpy(v52, "unknown"); /*0x6d6e4*/
  std::string::assign(a1 + 168, v52); /*0x6d6f0*/
  v50 = 0u; /*0x6d704*/
  v51 = 0u; /*0x6d704*/
  v48 = 0u; /*0x6d708*/
  v49 = 0u; /*0x6d708*/
  v46 = 0u; /*0x6d70c*/
  v47 = 0u; /*0x6d70c*/
  *(_OWORD *)v44 = 0u; /*0x6d710*/
  v45 = 0u; /*0x6d710*/
  __system_property_get("ro.product.brand", v44); /*0x6d714*/
  if ( !v44[0] ) /*0x6d71c*/
    strcpy(v44, "unknown"); /*0x6d720*/
  std::string::assign(a1 + 192, v44); /*0x6d72c*/
  v42 = 0u; /*0x6d740*/
  v43 = 0u; /*0x6d740*/
  v40 = 0u; /*0x6d744*/
  v41 = 0u; /*0x6d744*/
  v38 = 0u; /*0x6d748*/
  v39 = 0u; /*0x6d748*/
  *(_OWORD *)v36 = 0u; /*0x6d74c*/
  v37 = 0u; /*0x6d74c*/
  __system_property_get("ro.build.version.release", v36); /*0x6d750*/
  if ( !v36[0] ) /*0x6d758*/
    strcpy(v36, "unknown"); /*0x6d75c*/
  std::string::assign(a1 + 144, v36); /*0x6d76c*/
  v7 = (*(__int64 (__fastcall **)(__int64, __int64))(*(_QWORD *)a2 + 248LL))(a2, a4); /*0x6d788*/
  v8 = (*(__int64 (__fastcall **)(__int64, __int64, const char *, const char *))(*(_QWORD *)a2 + 264LL))( /*0x6d7a8*/
         a2,
         v7,
         "getPackageManager",
         "()Landroid/content/pm/PackageManager;");
  v9 = _JNIEnv::CallObjectMethod(a2, a4, v8); /*0x6d7c0*/
  v10 = (*(__int64 (__fastcall **)(__int64, __int64))(*(_QWORD *)a2 + 248LL))(a2, v9); /*0x6d7d0*/
  v11 = (*(__int64 (__fastcall **)(__int64, __int64, const char *, const char *))(*(_QWORD *)a2 + 264LL))( /*0x6d808*/
          a2,
          v10,
          "getPackageInfo",
          "(Ljava/lang/String;I)Landroid/content/pm/PackageInfo;");
  v12 = (*(__int64 (__fastcall **)(__int64, __int64, const char *, const char *))(*(_QWORD *)a2 + 264LL))( /*0x6d820*/
          a2,
          v7,
          "getPackageName",
          "()Ljava/lang/String;");
  _JNIEnv::CallObjectMethod(a2, a4, v12); /*0x6d830*/
  v13 = _JNIEnv::CallObjectMethod(a2, v9, v11); /*0x6d850*/
  v14 = (*(__int64 (__fastcall **)(__int64, __int64))(*(_QWORD *)a2 + 248LL))(a2, v13); /*0x6d868*/
  v15 = (*(__int64 (__fastcall **)(__int64, __int64, const char *, const char *))(*(_QWORD *)a2 + 752LL))( /*0x6d888*/
          a2,
          v14,
          "versionName",
          "Ljava/lang/String;");
  v16 = (*(__int64 (__fastcall **)(__int64, __int64, __int64))(*(_QWORD *)a2 + 760LL))(a2, v13, v15); /*0x6d8a0*/
  v17 = (char *)CenterDataAPI::jstringToChar(a1, a2, v16); /*0x6d8b0*/
  std::string::assign(a1 + 96, v17); /*0x6d8bc*/
  v18 = (*(__int64 (__fastcall **)(__int64, __int64, const char *, const char *))(*(_QWORD *)a2 + 752LL))( /*0x6d8e0*/
          a2,
          v14,
          "signatures",
          "[Landroid/content/pm/Signature;");
  v19 = (*(__int64 (__fastcall **)(__int64, __int64, __int64))(*(_QWORD *)a2 + 760LL))(a2, v13, v18); /*0x6d8f8*/
  v20 = (*(__int64 (__fastcall **)(__int64, __int64, _QWORD))(*(_QWORD *)a2 + 1384LL))(a2, v19, 0); /*0x6d918*/
  v21 = (*(__int64 (__fastcall **)(__int64, __int64))(*(_QWORD *)a2 + 248LL))(a2, v20); /*0x6d928*/
  v22 = (*(__int64 (__fastcall **)(__int64, __int64, const char *, const char *))(*(_QWORD *)a2 + 264LL))( /*0x6d948*/
          a2,
          v21,
          "toCharsString",
          "()Ljava/lang/String;");
  v23 = _JNIEnv::CallObjectMethod(a2, v20, v22); /*0x6d958*/
  v24 = (const char *)CenterDataAPI::jstringToChar(a1, a2, v23); /*0x6d96c*/
  v25 = strlen(v24); /*0x6d970*/
  if ( v25 >= 0xFFFFFFFFFFFFFFF0LL ) /*0x6d978*/
    std::__basic_string_common<true>::__throw_length_error(v32); /*0x6da58*/
  v26 = v25; /*0x6d97c*/
  if ( v25 >= 0x17 ) /*0x6d984*/
  {
    v28 = (v25 + 16) & 0xFFFFFFFFFFFFFFF0LL; /*0x6d9a4*/
    v27 = (char *)operator new(v28); /*0x6d9b4*/
    v32[1] = v26; /*0x6d9b8*/
    v33 = v27; /*0x6d9b8*/
    v32[0] = v28 | 1; /*0x6d9bc*/
    goto LABEL_14; /*0x6d9bc*/
  }
  v27 = (char *)v32 + 1; /*0x6d990*/
  LOBYTE(v32[0]) = 2 * v25; /*0x6d994*/
  if ( v25 ) /*0x6d998*/
LABEL_14:
    memcpy(v27, v24, v26); /*0x6d9c0*/
  v27[v26] = 0; /*0x6d9d0*/
  CenterDataAPI::Md5Encode(&v34, a1, v32); /*0x6d9e0*/
  if ( (*(_BYTE *)(a1 + 216) & 1) != 0 ) /*0x6d9ec*/
    operator delete(*(void **)(a1 + 232)); /*0x6d9f4*/
  v29 = v34; /*0x6d9f8*/
  LOWORD(v34) = 0; /*0x6d9fc*/
  v30 = v35; /*0x6da00*/
  v31 = v32[0]; /*0x6da04*/
  *(_OWORD *)(a1 + 216) = v29; /*0x6da08*/
  *(_QWORD *)(a1 + 232) = v30; /*0x6da0c*/
  if ( (v31 & 1) != 0 ) /*0x6da10*/
    operator delete(v33); /*0x6da18*/
  *(_BYTE *)(a1 + 240) = 1; /*0x6da20*/
}
