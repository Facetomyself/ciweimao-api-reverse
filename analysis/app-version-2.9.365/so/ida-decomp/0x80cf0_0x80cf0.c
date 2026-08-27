// 0x80cf0 @ 0x80cf0
char *__fastcall CenterDataAPI::getHead0(uint16x8_t *this)
{
  __int64 v2; // x0
  __int128 v3; // q0
  unsigned __int64 v4; // x8
  bool v5; // zf
  size_t v6; // x8
  char *v7; // x1
  size_t v8; // x2
  __int64 v9; // x0
  __int128 v10; // q0
  __int64 v11; // x0
  __int128 v12; // q0
  unsigned __int64 v13; // x8
  bool v14; // zf
  size_t v15; // x8
  char *v16; // x1
  size_t v17; // x2
  __int64 v18; // x0
  __int128 v19; // q0
  __int64 v20; // x0
  __int128 v21; // q0
  unsigned __int64 v22; // x8
  bool v23; // zf
  size_t v24; // x8
  char *v25; // x1
  size_t v26; // x2
  __int64 v27; // x0
  __int128 v28; // q0
  __int64 v29; // x0
  __int128 v30; // q0
  unsigned __int64 v31; // x8
  bool v32; // zf
  size_t v33; // x8
  char *v34; // x1
  size_t v35; // x2
  __int64 v36; // x0
  void *v37; // x8
  __int128 v38; // q0
  void *v39; // x19
  void *v41[3]; // [xsp+8h] [xbp-118h] BYREF
  __int128 v42; // [xsp+20h] [xbp-100h] BYREF
  void *v43; // [xsp+30h] [xbp-F0h]
  __int128 v44; // [xsp+40h] [xbp-E0h] BYREF
  void *v45; // [xsp+50h] [xbp-D0h]
  __int128 v46; // [xsp+60h] [xbp-C0h] BYREF
  void *v47; // [xsp+70h] [xbp-B0h]
  __int128 v48; // [xsp+80h] [xbp-A0h] BYREF
  void *v49; // [xsp+90h] [xbp-90h]
  __int128 v50; // [xsp+A0h] [xbp-80h] BYREF
  void *v51; // [xsp+B0h] [xbp-70h]
  __int128 v52; // [xsp+C0h] [xbp-60h] BYREF
  void *v53; // [xsp+D0h] [xbp-50h]
  __int128 v54; // [xsp+E0h] [xbp-40h] BYREF
  void *v55; // [xsp+F0h] [xbp-30h]
  __int128 v56; // [xsp+100h] [xbp-20h] BYREF
  void *v57; // [xsp+110h] [xbp-10h]
  __int64 v58; // [xsp+118h] [xbp-8h]

  v58 = *(_QWORD *)(_ReadStatusReg(TPIDR_EL0) + 40); /*0x80d1c*/
  std::operator+<char>(v41, "User-Agent: Android  com.kuangxiangciweimao.novel.c  ", this + 6);
  v2 = std::string::append((int)v41, ", "); /*0x80d34*/
  v3 = *(_OWORD *)v2; /*0x80d40*/
  v43 = *(void **)(v2 + 16); /*0x80d44*/
  v42 = v3; /*0x80d48*/
  *(_QWORD *)(v2 + 8) = 0; /*0x80d4c*/
  *(_QWORD *)(v2 + 16) = 0; /*0x80d4c*/
  *(_QWORD *)v2 = 0; /*0x80d50*/
  v4 = *((unsigned __int8 *)this + 192); /*0x80d58*/
  v5 = (v4 & 1) == 0; /*0x80d5c*/
  v6 = v4 >> 1; /*0x80d60*/
  if ( v5 ) /*0x80d64*/
    v7 = (char *)this + 193; /*0x80d64*/
  else
    v7 = *((char **)this + 26); /*0x80d64*/
  if ( v5 ) /*0x80d68*/
    v8 = v6; /*0x80d68*/
  else
    v8 = *((_QWORD *)this + 25); /*0x80d68*/
  v9 = std::string::append((int)&v42, v7, v8); /*0x80d70*/
  v10 = *(_OWORD *)v9; /*0x80d78*/
  v45 = *(void **)(v9 + 16); /*0x80d7c*/
  v44 = v10; /*0x80d80*/
  *(_QWORD *)(v9 + 8) = 0; /*0x80d84*/
  *(_QWORD *)(v9 + 16) = 0; /*0x80d84*/
  *(_QWORD *)v9 = 0; /*0x80d88*/
  v11 = std::string::append((int)&v44, ", "); /*0x80d98*/
  v12 = *(_OWORD *)v11; /*0x80da4*/
  v47 = *(void **)(v11 + 16); /*0x80da8*/
  v46 = v12; /*0x80dac*/
  *(_QWORD *)(v11 + 8) = 0; /*0x80db0*/
  *(_QWORD *)(v11 + 16) = 0; /*0x80db0*/
  *(_QWORD *)v11 = 0; /*0x80db4*/
  v13 = *((unsigned __int8 *)this + 168); /*0x80dbc*/
  v14 = (v13 & 1) == 0; /*0x80dc0*/
  v15 = v13 >> 1; /*0x80dc4*/
  if ( v14 ) /*0x80dc8*/
    v16 = (char *)this + 169; /*0x80dc8*/
  else
    v16 = *((char **)this + 23); /*0x80dc8*/
  if ( v14 ) /*0x80dcc*/
    v17 = v15; /*0x80dcc*/
  else
    v17 = *((_QWORD *)this + 22); /*0x80dcc*/
  v18 = std::string::append((int)&v46, v16, v17); /*0x80dd4*/
  v19 = *(_OWORD *)v18; /*0x80ddc*/
  v49 = *(void **)(v18 + 16); /*0x80de0*/
  v48 = v19; /*0x80de4*/
  *(_QWORD *)(v18 + 8) = 0; /*0x80de8*/
  *(_QWORD *)(v18 + 16) = 0; /*0x80de8*/
  *(_QWORD *)v18 = 0; /*0x80dec*/
  v20 = std::string::append((int)&v48, ", "); /*0x80dfc*/
  v21 = *(_OWORD *)v20; /*0x80e08*/
  v51 = *(void **)(v20 + 16); /*0x80e10*/
  v50 = v21; /*0x80e14*/
  *(_QWORD *)(v20 + 8) = 0; /*0x80e18*/
  *(_QWORD *)(v20 + 16) = 0; /*0x80e18*/
  *(_QWORD *)v20 = 0; /*0x80e1c*/
  v22 = *((unsigned __int8 *)this + 120); /*0x80e24*/
  v23 = (v22 & 1) == 0; /*0x80e28*/
  v24 = v22 >> 1; /*0x80e2c*/
  if ( v23 ) /*0x80e30*/
    v25 = (char *)this + 121; /*0x80e30*/
  else
    v25 = *((char **)this + 17); /*0x80e30*/
  if ( v23 ) /*0x80e34*/
    v26 = v24; /*0x80e34*/
  else
    v26 = *((_QWORD *)this + 16); /*0x80e34*/
  v27 = std::string::append((int)&v50, v25, v26); /*0x80e3c*/
  v28 = *(_OWORD *)v27; /*0x80e44*/
  v53 = *(void **)(v27 + 16); /*0x80e48*/
  v52 = v28; /*0x80e4c*/
  *(_QWORD *)(v27 + 8) = 0; /*0x80e50*/
  *(_QWORD *)(v27 + 16) = 0; /*0x80e50*/
  *(_QWORD *)v27 = 0; /*0x80e54*/
  v29 = std::string::append((int)&v52, ", "); /*0x80e64*/
  v30 = *(_OWORD *)v29; /*0x80e70*/
  v55 = *(void **)(v29 + 16); /*0x80e74*/
  v54 = v30; /*0x80e78*/
  *(_QWORD *)(v29 + 8) = 0; /*0x80e7c*/
  *(_QWORD *)(v29 + 16) = 0; /*0x80e7c*/
  *(_QWORD *)v29 = 0; /*0x80e80*/
  v31 = *((unsigned __int8 *)this + 144); /*0x80e88*/
  v32 = (v31 & 1) == 0; /*0x80e8c*/
  v33 = v31 >> 1; /*0x80e90*/
  if ( v32 ) /*0x80e94*/
    v34 = (char *)this + 145; /*0x80e94*/
  else
    v34 = *((char **)this + 20); /*0x80e94*/
  if ( v32 ) /*0x80e98*/
    v35 = v33; /*0x80e98*/
  else
    v35 = *((_QWORD *)this + 19); /*0x80e98*/
  v36 = std::string::append((int)&v54, v34, v35); /*0x80ea0*/
  v37 = *(void **)(v36 + 16); /*0x80ea4*/
  v38 = *(_OWORD *)v36; /*0x80ea8*/
  *(_QWORD *)v36 = 0; /*0x80eac*/
  *(_QWORD *)(v36 + 8) = 0; /*0x80eb0*/
  *(_QWORD *)(v36 + 16) = 0; /*0x80eb0*/
  v57 = v37; /*0x80eb8*/
  v56 = v38; /*0x80ebc*/
  if ( (v54 & 1) != 0 ) /*0x80ec0*/
  {
    operator delete(v55); /*0x80f14*/
    if ( (v52 & 1) == 0 ) /*0x80f1c*/
    {
LABEL_27:
      if ( (v50 & 1) == 0 ) /*0x80ed0*/
        goto LABEL_28; /*0x80ed0*/
      goto LABEL_37; /*0x80ed0*/
    }
  }
  else if ( (v52 & 1) == 0 ) /*0x80ec8*/
  {
    goto LABEL_27; /*0x80ec8*/
  }
  operator delete(v53); /*0x80f24*/
  if ( (v50 & 1) == 0 ) /*0x80f2c*/
  {
LABEL_28:
    if ( (v48 & 1) == 0 ) /*0x80ed8*/
      goto LABEL_29; /*0x80ed8*/
    goto LABEL_38; /*0x80ed8*/
  }
LABEL_37:
  operator delete(v51); /*0x80f30*/
  if ( (v48 & 1) == 0 ) /*0x80f3c*/
  {
LABEL_29:
    if ( (v46 & 1) == 0 ) /*0x80ee0*/
      goto LABEL_30; /*0x80ee0*/
    goto LABEL_39; /*0x80ee0*/
  }
LABEL_38:
  operator delete(v49); /*0x80f40*/
  if ( (v46 & 1) == 0 ) /*0x80f4c*/
  {
LABEL_30:
    if ( (v44 & 1) == 0 ) /*0x80ee8*/
      goto LABEL_31; /*0x80ee8*/
    goto LABEL_40; /*0x80ee8*/
  }
LABEL_39:
  operator delete(v47); /*0x80f50*/
  if ( (v44 & 1) == 0 ) /*0x80f5c*/
  {
LABEL_31:
    if ( (v42 & 1) == 0 ) /*0x80ef0*/
      goto LABEL_32; /*0x80ef0*/
    goto LABEL_41; /*0x80ef0*/
  }
LABEL_40:
  operator delete(v45); /*0x80f60*/
  if ( (v42 & 1) == 0 ) /*0x80f6c*/
  {
LABEL_32:
    if ( ((__int64)v41[0] & 1) == 0 ) /*0x80ef8*/
      goto LABEL_33; /*0x80ef8*/
LABEL_42:
    operator delete(v41[2]); /*0x80f80*/
    if ( (v56 & 1) == 0 ) /*0x80f8c*/
      return (char *)&v56 + 1; /*0x80f8c*/
LABEL_43:
    v39 = v57; /*0x80f90*/
    operator delete(v57); /*0x80f98*/
    return (char *)v39; /*0x80f98*/
  }
LABEL_41:
  operator delete(v43); /*0x80f70*/
  if ( ((__int64)v41[0] & 1) != 0 ) /*0x80f7c*/
    goto LABEL_42; /*0x80f7c*/
LABEL_33:
  if ( (v56 & 1) != 0 ) /*0x80f00*/
    goto LABEL_43; /*0x80f00*/
  return (char *)&v56 + 1; /*0x80fc0*/
}
