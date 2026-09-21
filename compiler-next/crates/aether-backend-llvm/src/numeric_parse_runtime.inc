
%struct.Big = type { [192 x i32], i32 }

; Function Attrs: nofree norecurse nosync nounwind sspstrong memory(argmem: read) uwtable
define internal { i32, i64 } @aether_numeric_parse_double(ptr noundef readonly captures(none) %0, i64 noundef %1) local_unnamed_addr #0 {
  %3 = alloca %struct.Big, align 4
  %4 = alloca %struct.Big, align 4
  %5 = alloca %struct.Big, align 4
  %6 = alloca %struct.Big, align 4
  %7 = alloca %struct.Big, align 4
  %8 = icmp eq i64 %1, 0
  br i1 %8, label %14, label %9

9:                                                ; preds = %2
  %10 = load i8, ptr %0, align 1
  switch i8 %10, label %14 [
    i8 43, label %11
    i8 45, label %11
  ]

11:                                               ; preds = %9, %9
  %12 = icmp eq i8 %10, 45
  %13 = select i1 %12, i64 -9223372036854775808, i64 0
  br label %14

14:                                               ; preds = %9, %11, %2
  %15 = phi i64 [ %13, %11 ], [ 0, %9 ], [ 0, %2 ]
  %16 = phi i64 [ 1, %11 ], [ 0, %9 ], [ 0, %2 ]
  call void @llvm.lifetime.start.p0(ptr nonnull %3) #6
  %17 = getelementptr inbounds nuw i8, ptr %3, i64 768
  %18 = icmp ult i64 %16, %1
  call void @llvm.memset.p0.i64(ptr noundef nonnull align 4 dereferenceable(772) %3, i8 0, i64 772, i1 false)
  br i1 %18, label %19, label %135

19:                                               ; preds = %14, %127
  %20 = phi i64 [ %128, %127 ], [ %16, %14 ]
  %21 = phi i32 [ %126, %127 ], [ 0, %14 ]
  %22 = phi i32 [ %125, %127 ], [ 0, %14 ]
  %23 = phi i32 [ %124, %127 ], [ 0, %14 ]
  %24 = phi i64 [ %123, %127 ], [ 0, %14 ]
  %25 = phi i64 [ %122, %127 ], [ 0, %14 ]
  %26 = phi i64 [ %120, %127 ], [ 0, %14 ]
  %27 = phi i32 [ %119, %127 ], [ 0, %14 ]
  %28 = getelementptr inbounds nuw i8, ptr %0, i64 %20
  %29 = load i8, ptr %28, align 1
  %30 = add i8 %29, -48
  %31 = icmp ult i8 %30, 10
  %32 = icmp ne i32 %23, 0
  br i1 %31, label %33, label %107

33:                                               ; preds = %19
  %34 = zext nneg i8 %29 to i32
  %35 = icmp ult i64 %24, 1000000
  %36 = select i1 %32, i1 %35, i1 false
  %37 = zext i1 %36 to i64
  %38 = add nuw nsw i64 %24, %37
  %39 = add nsw i32 %34, -48
  %40 = icmp ne i32 %22, 0
  %41 = icmp ne i32 %39, 0
  %42 = select i1 %40, i1 true, i1 %41
  br i1 %42, label %43, label %102

43:                                               ; preds = %33
  %44 = icmp ult i64 %25, 780
  br i1 %44, label %45, label %99

45:                                               ; preds = %43
  %46 = load i32, ptr %17, align 4
  %47 = icmp eq i32 %46, 0
  br i1 %47, label %48, label %54

48:                                               ; preds = %54, %45
  %49 = phi i64 [ 0, %45 ], [ %63, %54 ]
  %50 = phi i32 [ 0, %45 ], [ %65, %54 ]
  %51 = icmp ne i64 %49, 0
  %52 = icmp ult i32 %50, 192
  %53 = and i1 %51, %52
  br i1 %53, label %68, label %73

54:                                               ; preds = %45, %54
  %55 = phi i64 [ %64, %54 ], [ 0, %45 ]
  %56 = phi i64 [ %63, %54 ], [ 0, %45 ]
  %57 = getelementptr inbounds nuw i32, ptr %3, i64 %55
  %58 = load i32, ptr %57, align 4
  %59 = zext i32 %58 to i64
  %60 = mul nuw nsw i64 %59, 10
  %61 = add nuw nsw i64 %60, %56
  %62 = trunc i64 %61 to i32
  store i32 %62, ptr %57, align 4
  %63 = lshr i64 %61, 32
  %64 = add nuw nsw i64 %55, 1
  %65 = load i32, ptr %17, align 4
  %66 = zext i32 %65 to i64
  %67 = icmp samesign ult i64 %64, %66
  br i1 %67, label %54, label %48

68:                                               ; preds = %48
  %69 = trunc nuw nsw i64 %49 to i32
  %70 = add nuw nsw i32 %50, 1
  store i32 %70, ptr %17, align 4
  %71 = zext nneg i32 %50 to i64
  %72 = getelementptr inbounds nuw i32, ptr %3, i64 %71
  store i32 %69, ptr %72, align 4
  br label %73

73:                                               ; preds = %48, %68
  br i1 %41, label %74, label %97

74:                                               ; preds = %73
  %75 = zext nneg i32 %39 to i64
  br label %76

76:                                               ; preds = %82, %74
  %77 = phi i64 [ %88, %82 ], [ 0, %74 ]
  %78 = phi i64 [ 1, %82 ], [ %75, %74 ]
  %79 = load i32, ptr %17, align 4
  %80 = zext i32 %79 to i64
  %81 = icmp samesign ult i64 %77, %80
  br i1 %81, label %82, label %90

82:                                               ; preds = %76
  %83 = getelementptr inbounds nuw i32, ptr %3, i64 %77
  %84 = load i32, ptr %83, align 4
  %85 = zext i32 %84 to i64
  %86 = add nuw nsw i64 %78, %85
  %87 = trunc i64 %86 to i32
  store i32 %87, ptr %83, align 4
  %88 = add nuw nsw i64 %77, 1
  %89 = icmp samesign ult i64 %86, 4294967296
  br i1 %89, label %97, label %76

90:                                               ; preds = %76
  %91 = icmp ult i32 %79, 192
  br i1 %91, label %92, label %97

92:                                               ; preds = %90
  %93 = trunc nuw nsw i64 %78 to i32
  %94 = add nuw nsw i32 %79, 1
  store i32 %94, ptr %17, align 4
  %95 = zext nneg i32 %79 to i64
  %96 = getelementptr inbounds nuw i32, ptr %3, i64 %95
  store i32 %93, ptr %96, align 4
  br label %97

97:                                               ; preds = %82, %73, %90, %92
  %98 = add nuw nsw i64 %25, 1
  br label %102

99:                                               ; preds = %43
  %100 = add i64 %26, 1
  %101 = select i1 %41, i32 1, i32 %27
  br label %102

102:                                              ; preds = %99, %33, %97
  %103 = phi i32 [ %27, %33 ], [ %27, %97 ], [ %101, %99 ]
  %104 = phi i64 [ %26, %33 ], [ %26, %97 ], [ %100, %99 ]
  %105 = phi i64 [ %25, %33 ], [ %98, %97 ], [ %25, %99 ]
  %106 = phi i32 [ 0, %33 ], [ 1, %97 ], [ 1, %99 ]
  br i1 %42, label %110, label %118

107:                                              ; preds = %19
  %108 = icmp ne i8 %29, 46
  %109 = select i1 %108, i1 true, i1 %32
  br i1 %109, label %118, label %110

110:                                              ; preds = %107, %102
  %111 = phi i32 [ %103, %102 ], [ %27, %107 ]
  %112 = phi i64 [ %104, %102 ], [ %26, %107 ]
  %113 = phi i64 [ %105, %102 ], [ %25, %107 ]
  %114 = phi i64 [ %38, %102 ], [ %24, %107 ]
  %115 = phi i32 [ %23, %102 ], [ 1, %107 ]
  %116 = phi i32 [ %106, %102 ], [ %22, %107 ]
  %117 = phi i32 [ 1, %102 ], [ %21, %107 ]
  br label %118

118:                                              ; preds = %107, %102, %110
  %119 = phi i32 [ %111, %110 ], [ %103, %102 ], [ %27, %107 ]
  %120 = phi i64 [ %112, %110 ], [ %104, %102 ], [ %26, %107 ]
  %121 = phi i1 [ false, %110 ], [ false, %102 ], [ true, %107 ]
  %122 = phi i64 [ %113, %110 ], [ %105, %102 ], [ %25, %107 ]
  %123 = phi i64 [ %114, %110 ], [ %38, %102 ], [ %24, %107 ]
  %124 = phi i32 [ %115, %110 ], [ %23, %102 ], [ %23, %107 ]
  %125 = phi i32 [ %116, %110 ], [ %106, %102 ], [ %22, %107 ]
  %126 = phi i32 [ %117, %110 ], [ 1, %102 ], [ %21, %107 ]
  br i1 %121, label %130, label %127

127:                                              ; preds = %118
  %128 = add nuw i64 %20, 1
  %129 = icmp eq i64 %128, %1
  br i1 %129, label %130, label %19

130:                                              ; preds = %118, %127
  %131 = phi i64 [ %20, %118 ], [ %1, %127 ]
  %132 = icmp eq i32 %126, 0
  %133 = icmp eq i32 %125, 0
  %134 = icmp eq i32 %119, 0
  br label %135

135:                                              ; preds = %130, %14
  %136 = phi i64 [ %16, %14 ], [ %131, %130 ]
  %137 = phi i1 [ false, %14 ], [ %121, %130 ]
  %138 = phi i1 [ true, %14 ], [ %134, %130 ]
  %139 = phi i64 [ 0, %14 ], [ %120, %130 ]
  %140 = phi i64 [ 0, %14 ], [ %122, %130 ]
  %141 = phi i64 [ 0, %14 ], [ %123, %130 ]
  %142 = phi i1 [ true, %14 ], [ %133, %130 ]
  %143 = phi i1 [ true, %14 ], [ %132, %130 ]
  br i1 %143, label %505, label %144

144:                                              ; preds = %135
  br i1 %137, label %145, label %192

145:                                              ; preds = %144
  %146 = getelementptr inbounds nuw i8, ptr %0, i64 %136
  %147 = load i8, ptr %146, align 1
  switch i8 %147, label %192 [
    i8 101, label %148
    i8 69, label %148
  ]

148:                                              ; preds = %145, %145
  %149 = add i64 %136, 1
  %150 = icmp ult i64 %149, %1
  br i1 %150, label %151, label %158

151:                                              ; preds = %148
  %152 = getelementptr inbounds nuw i8, ptr %0, i64 %149
  %153 = load i8, ptr %152, align 1
  switch i8 %153, label %158 [
    i8 43, label %154
    i8 45, label %154
  ]

154:                                              ; preds = %151, %151
  %155 = icmp eq i8 %153, 45
  %156 = zext i1 %155 to i32
  %157 = add i64 %136, 2
  br label %158

158:                                              ; preds = %151, %154, %148
  %159 = phi i32 [ %156, %154 ], [ 0, %151 ], [ 0, %148 ]
  %160 = phi i64 [ %157, %154 ], [ %149, %151 ], [ %149, %148 ]
  %161 = icmp ult i64 %160, %1
  br i1 %161, label %162, label %188

162:                                              ; preds = %158
  %163 = getelementptr inbounds nuw i8, ptr %0, i64 %160
  %164 = load i8, ptr %163, align 1
  %165 = add i8 %164, -58
  %166 = icmp ult i8 %165, -10
  br i1 %166, label %188, label %172

167:                                              ; preds = %183
  %168 = getelementptr inbounds nuw i8, ptr %0, i64 %185
  %169 = load i8, ptr %168, align 1
  %170 = add i8 %169, -48
  %171 = icmp ult i8 %170, 10
  br i1 %171, label %172, label %188

172:                                              ; preds = %162, %167
  %173 = phi i8 [ %169, %167 ], [ %164, %162 ]
  %174 = phi i64 [ %184, %167 ], [ 0, %162 ]
  %175 = phi i64 [ %185, %167 ], [ %160, %162 ]
  %176 = icmp slt i64 %174, 1000000
  br i1 %176, label %177, label %183

177:                                              ; preds = %172
  %178 = mul nsw i64 %174, 10
  %179 = and i8 %173, 15
  %180 = zext nneg i8 %179 to i64
  %181 = add nsw i64 %178, %180
  %182 = tail call i64 @llvm.smin.i64(i64 %181, i64 1000000)
  br label %183

183:                                              ; preds = %172, %177
  %184 = phi i64 [ %182, %177 ], [ %174, %172 ]
  %185 = add nuw i64 %175, 1
  %186 = icmp eq i64 %185, %1
  br i1 %186, label %187, label %167

187:                                              ; preds = %183
  br label %188

188:                                              ; preds = %167, %162, %187, %158
  %189 = phi i64 [ 0, %158 ], [ 0, %162 ], [ %184, %187 ], [ %184, %167 ]
  %190 = phi i1 [ true, %158 ], [ true, %162 ], [ false, %187 ], [ false, %167 ]
  %191 = phi i64 [ %160, %158 ], [ %160, %162 ], [ %1, %187 ], [ %185, %167 ]
  br i1 %190, label %500, label %192

192:                                              ; preds = %145, %188, %144
  %193 = phi i64 [ %189, %188 ], [ 0, %145 ], [ 0, %144 ]
  %194 = phi i32 [ %159, %188 ], [ 0, %145 ], [ 0, %144 ]
  %195 = phi i64 [ %191, %188 ], [ %136, %145 ], [ %136, %144 ]
  %196 = icmp eq i64 %195, %1
  br i1 %196, label %197, label %500

197:                                              ; preds = %192
  br i1 %142, label %198, label %200

198:                                              ; preds = %197
  %199 = insertvalue { i32, i64 } { i32 0, i64 poison }, i64 %15, 1
  br label %496

200:                                              ; preds = %197
  %201 = icmp eq i32 %194, 0
  %202 = sub nsw i64 0, %193
  %203 = select i1 %201, i64 %193, i64 %202
  %204 = icmp slt i64 %141, 0
  %205 = add nsw i64 %141, 1000000
  %206 = icmp sgt i64 %203, %205
  %207 = select i1 %204, i1 %206, i1 false
  br i1 %207, label %215, label %208

208:                                              ; preds = %200
  %209 = icmp sgt i64 %141, 0
  %210 = add nsw i64 %141, -1000000
  %211 = icmp slt i64 %203, %210
  %212 = select i1 %209, i1 %211, i1 false
  %213 = sub nsw i64 %203, %141
  %214 = select i1 %212, i64 -1000000, i64 %213
  br label %215

215:                                              ; preds = %200, %208
  %216 = phi i64 [ %214, %208 ], [ 1000000, %200 ]
  %217 = icmp sgt i64 %139, 0
  %218 = sub nsw i64 1000000, %139
  %219 = icmp sgt i64 %216, %218
  %220 = select i1 %217, i1 %219, i1 false
  br i1 %220, label %228, label %221

221:                                              ; preds = %215
  %222 = icmp slt i64 %139, 0
  %223 = sub nsw i64 -1000000, %139
  %224 = icmp slt i64 %216, %223
  %225 = select i1 %222, i1 %224, i1 false
  %226 = add nsw i64 %216, %139
  %227 = select i1 %225, i64 -1000000, i64 %226
  br label %228

228:                                              ; preds = %215, %221
  %229 = phi i64 [ %227, %221 ], [ 1000000, %215 ]
  %230 = icmp sgt i64 %229, 1
  %231 = sub nsw i64 1000001, %229
  %232 = icmp sgt i64 %140, %231
  %233 = select i1 %230, i1 %232, i1 false
  br i1 %233, label %242, label %234

234:                                              ; preds = %228
  %235 = icmp slt i64 %229, 1
  %236 = sub nsw i64 -999999, %229
  %237 = icmp slt i64 %140, %236
  %238 = select i1 %235, i1 %237, i1 false
  %239 = add i64 %140, -1
  %240 = add i64 %239, %229
  %241 = select i1 %238, i64 -1000000, i64 %240
  br label %242

242:                                              ; preds = %228, %234
  %243 = phi i64 [ %241, %234 ], [ 1000000, %228 ]
  %244 = icmp sgt i64 %243, 309
  br i1 %244, label %496, label %245

245:                                              ; preds = %242
  %246 = icmp slt i64 %243, -324
  br i1 %246, label %496, label %247

247:                                              ; preds = %245
  %248 = icmp sgt i64 %229, -1
  br i1 %248, label %249, label %375

249:                                              ; preds = %247
  %250 = icmp eq i64 %229, 0
  br i1 %250, label %251, label %279

251:                                              ; preds = %308, %249
  %252 = load i32, ptr %17, align 4
  %253 = icmp eq i32 %252, 0
  br i1 %253, label %275, label %254

254:                                              ; preds = %251
  %255 = add i32 %252, -1
  %256 = shl i32 %255, 5
  %257 = add i32 %256, 32
  %258 = zext i32 %255 to i64
  %259 = getelementptr inbounds nuw i32, ptr %3, i64 %258
  %260 = load i32, ptr %259, align 4
  %261 = icmp eq i32 %260, 0
  br i1 %261, label %272, label %262

262:                                              ; preds = %254
  %263 = icmp sgt i32 %260, -1
  br i1 %263, label %264, label %272

264:                                              ; preds = %262, %264
  %265 = phi i32 [ %268, %264 ], [ 0, %262 ]
  %266 = phi i32 [ %267, %264 ], [ %260, %262 ]
  %267 = shl nuw i32 %266, 1
  %268 = add i32 %265, 1
  %269 = icmp sgt i32 %267, -1
  br i1 %269, label %264, label %270

270:                                              ; preds = %264
  %271 = xor i32 %265, -1
  br label %272

272:                                              ; preds = %270, %262, %254
  %273 = phi i32 [ -32, %254 ], [ 0, %262 ], [ %271, %270 ]
  %274 = add i32 %257, %273
  br label %275

275:                                              ; preds = %251, %272
  %276 = phi i32 [ %274, %272 ], [ 0, %251 ]
  %277 = tail call i32 @llvm.usub.sat.i32(i32 %276, i32 53)
  %278 = icmp ult i32 %276, 54
  br i1 %278, label %333, label %311

279:                                              ; preds = %249, %308
  %280 = phi i64 [ %309, %308 ], [ 0, %249 ]
  %281 = load i32, ptr %17, align 4
  %282 = icmp eq i32 %281, 0
  br i1 %282, label %283, label %289

283:                                              ; preds = %289, %279
  %284 = phi i64 [ 0, %279 ], [ %298, %289 ]
  %285 = phi i32 [ 0, %279 ], [ %300, %289 ]
  %286 = icmp ne i64 %284, 0
  %287 = icmp ult i32 %285, 192
  %288 = and i1 %286, %287
  br i1 %288, label %303, label %308

289:                                              ; preds = %279, %289
  %290 = phi i64 [ %299, %289 ], [ 0, %279 ]
  %291 = phi i64 [ %298, %289 ], [ 0, %279 ]
  %292 = getelementptr inbounds nuw i32, ptr %3, i64 %290
  %293 = load i32, ptr %292, align 4
  %294 = zext i32 %293 to i64
  %295 = mul nuw nsw i64 %294, 5
  %296 = add nuw nsw i64 %295, %291
  %297 = trunc i64 %296 to i32
  store i32 %297, ptr %292, align 4
  %298 = lshr i64 %296, 32
  %299 = add nuw nsw i64 %290, 1
  %300 = load i32, ptr %17, align 4
  %301 = zext i32 %300 to i64
  %302 = icmp samesign ult i64 %299, %301
  br i1 %302, label %289, label %283

303:                                              ; preds = %283
  %304 = trunc nuw nsw i64 %284 to i32
  %305 = add nuw nsw i32 %285, 1
  store i32 %305, ptr %17, align 4
  %306 = zext nneg i32 %285 to i64
  %307 = getelementptr inbounds nuw i32, ptr %3, i64 %306
  store i32 %304, ptr %307, align 4
  br label %308

308:                                              ; preds = %283, %303
  %309 = add nuw nsw i64 %280, 1
  %310 = icmp eq i64 %309, %229
  br i1 %310, label %251, label %279

311:                                              ; preds = %275, %326
  %312 = phi i64 [ %331, %326 ], [ 0, %275 ]
  %313 = phi i64 [ %330, %326 ], [ 0, %275 ]
  %314 = trunc nuw nsw i64 %312 to i32
  %315 = add i32 %277, %314
  %316 = lshr i32 %315, 5
  %317 = icmp ult i32 %316, %252
  br i1 %317, label %318, label %326

318:                                              ; preds = %311
  %319 = zext nneg i32 %316 to i64
  %320 = getelementptr inbounds nuw i32, ptr %3, i64 %319
  %321 = load i32, ptr %320, align 4
  %322 = and i32 %315, 31
  %323 = shl nuw i32 1, %322
  %324 = and i32 %321, %323
  %325 = icmp eq i32 %324, 0
  br label %326

326:                                              ; preds = %318, %311
  %327 = phi i1 [ %325, %318 ], [ true, %311 ]
  %328 = shl nuw nsw i64 1, %312
  %329 = select i1 %327, i64 0, i64 %328
  %330 = or i64 %329, %313
  %331 = add nuw nsw i64 %312, 1
  %332 = icmp eq i64 %331, 53
  br i1 %332, label %347, label %311

333:                                              ; preds = %275
  %334 = load i32, ptr %3, align 4
  %335 = select i1 %253, i32 0, i32 %334
  %336 = zext i32 %335 to i64
  %337 = icmp ugt i32 %252, 1
  %338 = getelementptr inbounds nuw i8, ptr %3, i64 4
  %339 = load i32, ptr %338, align 4
  %340 = zext i32 %339 to i64
  %341 = shl nuw i64 %340, 32
  %342 = select i1 %337, i64 %341, i64 0
  %343 = or disjoint i64 %342, %336
  %344 = sub nuw nsw i32 53, %276
  %345 = zext nneg i32 %344 to i64
  %346 = shl i64 %343, %345
  br label %347

347:                                              ; preds = %326, %333
  %348 = phi i64 [ %346, %333 ], [ %330, %326 ]
  br i1 %278, label %360, label %349

349:                                              ; preds = %347
  %350 = call fastcc i32 @low_half_cmp(ptr noundef %3, i32 noundef %277)
  %351 = icmp sgt i32 %350, 0
  br i1 %351, label %358, label %352

352:                                              ; preds = %349
  %353 = icmp eq i32 %350, 0
  br i1 %353, label %354, label %360

354:                                              ; preds = %352
  %355 = and i64 %348, 1
  %356 = icmp eq i64 %355, 0
  %357 = select i1 %138, i1 %356, i1 false
  br i1 %357, label %360, label %358

358:                                              ; preds = %354, %349
  %359 = add i64 %348, 1
  br label %360

360:                                              ; preds = %352, %358, %354, %347
  %361 = phi i64 [ %348, %347 ], [ %359, %358 ], [ %348, %354 ], [ %348, %352 ]
  %362 = zext i32 %276 to i64
  %363 = icmp ne i64 %361, 9007199254740992
  %364 = sext i1 %363 to i64
  %365 = add nuw i64 %229, %362
  %366 = add i64 %365, %364
  %367 = icmp sgt i64 %366, 1023
  br i1 %367, label %496, label %368

368:                                              ; preds = %360
  %369 = shl i64 %366, 52
  %370 = add i64 %369, 4607182418800017408
  %371 = and i64 %361, 4503599627370495
  %372 = or disjoint i64 %370, %371
  %373 = or i64 %372, %15
  %374 = insertvalue { i32, i64 } { i32 0, i64 poison }, i64 %373, 1
  br label %496

375:                                              ; preds = %247
  %376 = trunc i64 %229 to i32
  %377 = sub i32 0, %376
  call void @llvm.lifetime.start.p0(ptr nonnull %4) #6
  call void @llvm.memset.p0.i64(ptr noundef nonnull align 4 dereferenceable(768) %4, i8 0, i64 768, i1 false)
  %378 = getelementptr inbounds nuw i8, ptr %4, i64 768
  store i32 1, ptr %378, align 4
  store i32 1, ptr %4, align 4
  %379 = icmp eq i32 %376, 0
  br i1 %379, label %380, label %397

380:                                              ; preds = %426, %375
  %381 = call fastcc i32 @bits(ptr noundef %3)
  %382 = zext i32 %381 to i64
  %383 = call fastcc i32 @bits(ptr noundef %4)
  %384 = zext i32 %383 to i64
  %385 = sub nsw i64 %382, %384
  %386 = call fastcc i32 @cmp_shift(ptr noundef %3, ptr noundef %4, i64 noundef %385)
  %387 = ashr i32 %386, 31
  %388 = sext i32 %387 to i64
  %389 = add nsw i64 %385, %388
  %390 = zext i32 %377 to i64
  %391 = sub nsw i64 %389, %390
  %392 = icmp sgt i64 %391, -1023
  %393 = sub nsw i64 52, %389
  %394 = sub nsw i64 1074, %390
  %395 = select i1 %392, i64 %393, i64 %394
  call void @llvm.lifetime.start.p0(ptr nonnull %6) #6
  %396 = icmp sgt i64 %395, -1
  br i1 %396, label %429, label %431

397:                                              ; preds = %375, %426
  %398 = phi i32 [ %427, %426 ], [ 0, %375 ]
  %399 = load i32, ptr %378, align 4
  %400 = icmp eq i32 %399, 0
  br i1 %400, label %401, label %407

401:                                              ; preds = %407, %397
  %402 = phi i64 [ 0, %397 ], [ %416, %407 ]
  %403 = phi i32 [ 0, %397 ], [ %418, %407 ]
  %404 = icmp ne i64 %402, 0
  %405 = icmp ult i32 %403, 192
  %406 = and i1 %404, %405
  br i1 %406, label %421, label %426

407:                                              ; preds = %397, %407
  %408 = phi i64 [ %417, %407 ], [ 0, %397 ]
  %409 = phi i64 [ %416, %407 ], [ 0, %397 ]
  %410 = getelementptr inbounds nuw i32, ptr %4, i64 %408
  %411 = load i32, ptr %410, align 4
  %412 = zext i32 %411 to i64
  %413 = mul nuw nsw i64 %412, 5
  %414 = add nuw nsw i64 %413, %409
  %415 = trunc i64 %414 to i32
  store i32 %415, ptr %410, align 4
  %416 = lshr i64 %414, 32
  %417 = add nuw nsw i64 %408, 1
  %418 = load i32, ptr %378, align 4
  %419 = zext i32 %418 to i64
  %420 = icmp samesign ult i64 %417, %419
  br i1 %420, label %407, label %401

421:                                              ; preds = %401
  %422 = trunc nuw nsw i64 %402 to i32
  %423 = add nuw nsw i32 %403, 1
  store i32 %423, ptr %378, align 4
  %424 = zext nneg i32 %403 to i64
  %425 = getelementptr inbounds nuw i32, ptr %4, i64 %424
  store i32 %422, ptr %425, align 4
  br label %426

426:                                              ; preds = %401, %421
  %427 = add nuw i32 %398, 1
  %428 = icmp eq i32 %427, %377
  br i1 %428, label %380, label %397

429:                                              ; preds = %380
  %430 = trunc i64 %395 to i32
  call fastcc void @shl(ptr noundef %5, ptr noundef %3, i32 noundef %430)
  call void @llvm.memcpy.p0.p0.i64(ptr noundef nonnull align 4 dereferenceable(772) %6, ptr noundef nonnull align 4 dereferenceable(772) %4, i64 772, i1 false)
  br label %434

431:                                              ; preds = %380
  call void @llvm.memcpy.p0.p0.i64(ptr noundef nonnull align 4 dereferenceable(772) %5, ptr noundef nonnull align 4 dereferenceable(772) %3, i64 772, i1 false)
  %432 = trunc i64 %395 to i32
  %433 = sub i32 0, %432
  call fastcc void @shl(ptr noundef %6, ptr noundef %4, i32 noundef %433)
  br label %434

434:                                              ; preds = %431, %429
  %435 = call fastcc i64 @quotient(ptr noundef %5, ptr noundef %6)
  call void @llvm.lifetime.start.p0(ptr nonnull %7) #6
  call fastcc void @shl(ptr noundef %7, ptr noundef %5, i32 noundef 1)
  %436 = getelementptr inbounds nuw i8, ptr %7, i64 768
  %437 = load i32, ptr %436, align 4
  %438 = getelementptr inbounds nuw i8, ptr %6, i64 768
  %439 = load i32, ptr %438, align 4
  %440 = icmp eq i32 %437, %439
  br i1 %440, label %441, label %443

441:                                              ; preds = %434
  %442 = zext i32 %437 to i64
  br label %446

443:                                              ; preds = %434
  %444 = icmp ugt i32 %437, %439
  %445 = select i1 %444, i32 1, i32 -1
  br label %459

446:                                              ; preds = %449, %441
  %447 = phi i64 [ %442, %441 ], [ %450, %449 ]
  %448 = icmp eq i64 %447, 0
  br i1 %448, label %459, label %449

449:                                              ; preds = %446
  %450 = add nsw i64 %447, -1
  %451 = getelementptr inbounds nuw i32, ptr %7, i64 %450
  %452 = load i32, ptr %451, align 4
  %453 = getelementptr inbounds nuw i32, ptr %6, i64 %450
  %454 = load i32, ptr %453, align 4
  %455 = icmp eq i32 %452, %454
  br i1 %455, label %446, label %456

456:                                              ; preds = %449
  %457 = icmp ugt i32 %452, %454
  %458 = select i1 %457, i32 1, i32 -1
  br label %459

459:                                              ; preds = %446, %443, %456
  %460 = phi i32 [ %445, %443 ], [ %458, %456 ], [ 0, %446 ]
  %461 = icmp sgt i32 %460, 0
  br i1 %461, label %468, label %462

462:                                              ; preds = %459
  %463 = icmp eq i32 %460, 0
  br i1 %463, label %464, label %470

464:                                              ; preds = %462
  %465 = and i64 %435, 1
  %466 = icmp eq i64 %465, 0
  %467 = select i1 %138, i1 %466, i1 false
  br i1 %467, label %470, label %468

468:                                              ; preds = %464, %459
  %469 = add i64 %435, 1
  br label %470

470:                                              ; preds = %464, %468, %462
  %471 = phi i64 [ %469, %468 ], [ %435, %464 ], [ %435, %462 ]
  br i1 %392, label %472, label %484

472:                                              ; preds = %470
  %473 = icmp eq i64 %471, 9007199254740992
  %474 = zext i1 %473 to i64
  %475 = add nsw i64 %391, %474
  %476 = icmp sgt i64 %475, 1023
  br i1 %476, label %494, label %477

477:                                              ; preds = %472
  %478 = shl nsw i64 %475, 52
  %479 = add i64 %478, 4607182418800017408
  %480 = and i64 %471, 4503599627370495
  %481 = or disjoint i64 %479, %480
  %482 = or i64 %481, %15
  %483 = insertvalue { i32, i64 } { i32 0, i64 poison }, i64 %482, 1
  br label %494

484:                                              ; preds = %470
  %485 = icmp eq i64 %471, 0
  br i1 %485, label %494, label %486

486:                                              ; preds = %484
  %487 = icmp ugt i64 %471, 4503599627370495
  br i1 %487, label %488, label %491

488:                                              ; preds = %486
  %489 = or disjoint i64 %15, 4503599627370496
  %490 = insertvalue { i32, i64 } { i32 0, i64 poison }, i64 %489, 1
  br label %494

491:                                              ; preds = %486
  %492 = or disjoint i64 %471, %15
  %493 = insertvalue { i32, i64 } { i32 0, i64 poison }, i64 %492, 1
  br label %494

494:                                              ; preds = %484, %472, %491, %488, %477
  %495 = phi { i32, i64 } [ { i32 2, i64 0 }, %472 ], [ %483, %477 ], [ %490, %488 ], [ %493, %491 ], [ { i32 3, i64 0 }, %484 ]
  call void @llvm.lifetime.end.p0(ptr nonnull %7) #6
  call void @llvm.lifetime.end.p0(ptr nonnull %6) #6
  call void @llvm.lifetime.end.p0(ptr nonnull %4) #6
  br label %496

496:                                              ; preds = %360, %245, %242, %368, %494, %198
  %497 = phi { i32, i64 } [ %199, %198 ], [ %374, %368 ], [ { i32 2, i64 0 }, %242 ], [ %495, %494 ], [ { i32 3, i64 0 }, %245 ], [ { i32 2, i64 0 }, %360 ]
  %498 = extractvalue { i32, i64 } %497, 1
  %499 = extractvalue { i32, i64 } %497, 0
  br label %500

500:                                              ; preds = %192, %188, %496
  %501 = phi i32 [ 1, %188 ], [ %499, %496 ], [ 1, %192 ]
  %502 = phi i64 [ 0, %188 ], [ %498, %496 ], [ 0, %192 ]
  %503 = insertvalue { i32, i64 } poison, i32 %501, 0
  %504 = insertvalue { i32, i64 } %503, i64 %502, 1
  br label %505

505:                                              ; preds = %135, %500
  %506 = phi { i32, i64 } [ %504, %500 ], [ { i32 1, i64 0 }, %135 ]
  call void @llvm.lifetime.end.p0(ptr nonnull %3) #6
  ret { i32, i64 } %506
}

; Function Attrs: mustprogress nocallback nofree nosync nounwind willreturn memory(argmem: readwrite)
declare void @llvm.lifetime.start.p0(ptr captures(none)) #1

; Function Attrs: mustprogress nocallback nofree nosync nounwind willreturn memory(argmem: readwrite)
declare void @llvm.lifetime.end.p0(ptr captures(none)) #1

; Function Attrs: nofree norecurse nosync nounwind sspstrong memory(argmem: read) uwtable
define internal fastcc i32 @bits(ptr noundef nonnull readonly captures(none) %0) unnamed_addr #0 {
  %2 = getelementptr inbounds nuw i8, ptr %0, i64 768
  %3 = load i32, ptr %2, align 4
  %4 = icmp eq i32 %3, 0
  br i1 %4, label %26, label %5

5:                                                ; preds = %1
  %6 = add i32 %3, -1
  %7 = shl i32 %6, 5
  %8 = add i32 %7, 32
  %9 = zext i32 %6 to i64
  %10 = getelementptr inbounds nuw i32, ptr %0, i64 %9
  %11 = load i32, ptr %10, align 4
  %12 = icmp eq i32 %11, 0
  br i1 %12, label %23, label %13

13:                                               ; preds = %5
  %14 = icmp sgt i32 %11, -1
  br i1 %14, label %15, label %23

15:                                               ; preds = %13, %15
  %16 = phi i32 [ %19, %15 ], [ 0, %13 ]
  %17 = phi i32 [ %18, %15 ], [ %11, %13 ]
  %18 = shl nuw i32 %17, 1
  %19 = add i32 %16, 1
  %20 = icmp sgt i32 %18, -1
  br i1 %20, label %15, label %21

21:                                               ; preds = %15
  %22 = xor i32 %16, -1
  br label %23

23:                                               ; preds = %21, %5, %13
  %24 = phi i32 [ -32, %5 ], [ 0, %13 ], [ %22, %21 ]
  %25 = add i32 %8, %24
  br label %26

26:                                               ; preds = %1, %23
  %27 = phi i32 [ %25, %23 ], [ 0, %1 ]
  ret i32 %27
}

; Function Attrs: nofree norecurse nosync nounwind sspstrong memory(argmem: read) uwtable
define internal fastcc range(i32 -1, 2) i32 @low_half_cmp(ptr noundef nonnull readonly captures(none) %0, i32 noundef range(i32 1, 0) %1) unnamed_addr #0 {
  %3 = add i32 %1, -1
  %4 = lshr i32 %3, 5
  %5 = and i32 %3, 31
  %6 = getelementptr inbounds nuw i8, ptr %0, i64 768
  %7 = load i32, ptr %6, align 4
  %8 = icmp ult i32 %4, %7
  br i1 %8, label %9, label %34

9:                                                ; preds = %2
  %10 = zext nneg i32 %4 to i64
  %11 = getelementptr inbounds nuw i32, ptr %0, i64 %10
  %12 = load i32, ptr %11, align 4
  %13 = shl nuw i32 1, %5
  %14 = and i32 %12, %13
  %15 = icmp eq i32 %14, 0
  br i1 %15, label %34, label %16

16:                                               ; preds = %9
  %17 = shl nsw i32 -1, %5
  %18 = xor i32 %17, -1
  %19 = and i32 %12, %18
  %20 = icmp eq i32 %19, 0
  br i1 %20, label %21, label %34

21:                                               ; preds = %16
  %22 = icmp eq i32 %4, 0
  br i1 %22, label %34, label %23

23:                                               ; preds = %21
  %24 = tail call i32 @llvm.umin.i32(i32 %4, i32 %7)
  %25 = zext nneg i32 %24 to i64
  br label %29

26:                                               ; preds = %29
  %27 = add nuw nsw i64 %30, 1
  %28 = icmp eq i64 %27, %25
  br i1 %28, label %34, label %29

29:                                               ; preds = %23, %26
  %30 = phi i64 [ 0, %23 ], [ %27, %26 ]
  %31 = getelementptr inbounds nuw i32, ptr %0, i64 %30
  %32 = load i32, ptr %31, align 4
  %33 = icmp eq i32 %32, 0
  br i1 %33, label %26, label %34

34:                                               ; preds = %29, %26, %21, %2, %9, %16
  %35 = phi i32 [ -1, %9 ], [ -1, %2 ], [ 1, %16 ], [ 0, %21 ], [ 0, %26 ], [ 1, %29 ]
  ret i32 %35
}

; Function Attrs: nofree norecurse nosync nounwind sspstrong memory(argmem: read) uwtable
define internal fastcc range(i32 -1, 2) i32 @cmp_shift(ptr noundef nonnull readonly captures(none) %0, ptr noundef nonnull readonly captures(none) %1, i64 noundef range(i64 -4294967295, 4294967296) %2) unnamed_addr #0 {
  %4 = alloca %struct.Big, align 4
  call void @llvm.lifetime.start.p0(ptr nonnull %4) #6
  %5 = icmp sgt i64 %2, -1
  %6 = trunc i64 %2 to i32
  br i1 %5, label %7, label %87

7:                                                ; preds = %3
  %8 = getelementptr inbounds nuw i8, ptr %4, i64 768
  %9 = lshr i32 %6, 5
  %10 = and i32 %6, 31
  %11 = getelementptr inbounds nuw i8, ptr %1, i64 768
  call void @llvm.memset.p0.i64(ptr noundef nonnull align 4 dereferenceable(772) %4, i8 0, i64 772, i1 false)
  %12 = load i32, ptr %11, align 4
  %13 = icmp ne i32 %10, 0
  %14 = zext i1 %13 to i32
  %15 = add nuw nsw i32 %9, %14
  %16 = add i32 %15, %12
  %17 = icmp ugt i32 %16, 192
  br i1 %17, label %64, label %18

18:                                               ; preds = %7
  %19 = icmp eq i32 %12, 0
  br i1 %19, label %23, label %20

20:                                               ; preds = %18
  %21 = and i64 %2, 31
  %22 = zext i32 %12 to i64
  br label %28

23:                                               ; preds = %28, %18
  %24 = phi i64 [ 0, %18 ], [ %41, %28 ]
  %25 = phi i32 [ 0, %18 ], [ %12, %28 ]
  %26 = add i32 %25, %9
  store i32 %26, ptr %8, align 4
  %27 = icmp eq i64 %24, 0
  br i1 %27, label %49, label %44

28:                                               ; preds = %28, %20
  %29 = phi i64 [ 0, %20 ], [ %42, %28 ]
  %30 = phi i64 [ 0, %20 ], [ %41, %28 ]
  %31 = getelementptr inbounds nuw i32, ptr %1, i64 %29
  %32 = load i32, ptr %31, align 4
  %33 = zext i32 %32 to i64
  %34 = shl nuw nsw i64 %33, %21
  %35 = or i64 %34, %30
  %36 = trunc i64 %35 to i32
  %37 = trunc nuw i64 %29 to i32
  %38 = add i32 %9, %37
  %39 = zext i32 %38 to i64
  %40 = getelementptr inbounds nuw i32, ptr %4, i64 %39
  store i32 %36, ptr %40, align 4
  %41 = lshr i64 %34, 32
  %42 = add nuw nsw i64 %29, 1
  %43 = icmp eq i64 %42, %22
  br i1 %43, label %23, label %28

44:                                               ; preds = %23
  %45 = trunc nuw nsw i64 %24 to i32
  %46 = add i32 %26, 1
  store i32 %46, ptr %8, align 4
  %47 = zext i32 %26 to i64
  %48 = getelementptr inbounds nuw i32, ptr %4, i64 %47
  store i32 %45, ptr %48, align 4
  br label %49

49:                                               ; preds = %44, %23
  %50 = load i32, ptr %8, align 4
  %51 = icmp eq i32 %50, 0
  br i1 %51, label %64, label %52

52:                                               ; preds = %49
  %53 = zext i32 %50 to i64
  br label %54

54:                                               ; preds = %61, %52
  %55 = phi i64 [ %53, %52 ], [ %56, %61 ]
  %56 = add nsw i64 %55, -1
  %57 = and i64 %56, 4294967295
  %58 = getelementptr inbounds nuw i32, ptr %4, i64 %57
  %59 = load i32, ptr %58, align 4
  %60 = icmp eq i32 %59, 0
  br i1 %60, label %61, label %64

61:                                               ; preds = %54
  %62 = trunc i64 %56 to i32
  store i32 %62, ptr %8, align 4
  %63 = icmp eq i32 %62, 0
  br i1 %63, label %64, label %54

64:                                               ; preds = %54, %61, %7, %49
  %65 = getelementptr inbounds nuw i8, ptr %0, i64 768
  %66 = load i32, ptr %65, align 4
  %67 = load i32, ptr %8, align 4
  %68 = icmp eq i32 %66, %67
  br i1 %68, label %69, label %71

69:                                               ; preds = %64
  %70 = zext i32 %66 to i64
  br label %74

71:                                               ; preds = %64
  %72 = icmp ugt i32 %66, %67
  %73 = select i1 %72, i32 1, i32 -1
  br label %168

74:                                               ; preds = %77, %69
  %75 = phi i64 [ %70, %69 ], [ %78, %77 ]
  %76 = icmp eq i64 %75, 0
  br i1 %76, label %168, label %77

77:                                               ; preds = %74
  %78 = add nsw i64 %75, -1
  %79 = getelementptr inbounds nuw i32, ptr %0, i64 %78
  %80 = load i32, ptr %79, align 4
  %81 = getelementptr inbounds nuw i32, ptr %4, i64 %78
  %82 = load i32, ptr %81, align 4
  %83 = icmp eq i32 %80, %82
  br i1 %83, label %74, label %84

84:                                               ; preds = %77
  %85 = icmp ugt i32 %80, %82
  %86 = select i1 %85, i32 1, i32 -1
  br label %168

87:                                               ; preds = %3
  %88 = sub i32 0, %6
  %89 = getelementptr inbounds nuw i8, ptr %4, i64 768
  %90 = lshr i32 %88, 5
  %91 = and i32 %88, 31
  %92 = getelementptr inbounds nuw i8, ptr %0, i64 768
  call void @llvm.memset.p0.i64(ptr noundef nonnull align 4 dereferenceable(772) %4, i8 0, i64 772, i1 false)
  %93 = load i32, ptr %92, align 4
  %94 = icmp ne i32 %91, 0
  %95 = zext i1 %94 to i32
  %96 = add nuw nsw i32 %90, %95
  %97 = add i32 %96, %93
  %98 = icmp ugt i32 %97, 192
  br i1 %98, label %145, label %99

99:                                               ; preds = %87
  %100 = icmp eq i32 %93, 0
  br i1 %100, label %104, label %101

101:                                              ; preds = %99
  %102 = zext nneg i32 %91 to i64
  %103 = zext i32 %93 to i64
  br label %109

104:                                              ; preds = %109, %99
  %105 = phi i64 [ 0, %99 ], [ %122, %109 ]
  %106 = phi i32 [ 0, %99 ], [ %93, %109 ]
  %107 = add i32 %106, %90
  store i32 %107, ptr %89, align 4
  %108 = icmp eq i64 %105, 0
  br i1 %108, label %130, label %125

109:                                              ; preds = %109, %101
  %110 = phi i64 [ 0, %101 ], [ %123, %109 ]
  %111 = phi i64 [ 0, %101 ], [ %122, %109 ]
  %112 = getelementptr inbounds nuw i32, ptr %0, i64 %110
  %113 = load i32, ptr %112, align 4
  %114 = zext i32 %113 to i64
  %115 = shl nuw nsw i64 %114, %102
  %116 = or i64 %115, %111
  %117 = trunc i64 %116 to i32
  %118 = trunc nuw i64 %110 to i32
  %119 = add i32 %90, %118
  %120 = zext i32 %119 to i64
  %121 = getelementptr inbounds nuw i32, ptr %4, i64 %120
  store i32 %117, ptr %121, align 4
  %122 = lshr i64 %115, 32
  %123 = add nuw nsw i64 %110, 1
  %124 = icmp eq i64 %123, %103
  br i1 %124, label %104, label %109

125:                                              ; preds = %104
  %126 = trunc nuw nsw i64 %105 to i32
  %127 = add i32 %107, 1
  store i32 %127, ptr %89, align 4
  %128 = zext i32 %107 to i64
  %129 = getelementptr inbounds nuw i32, ptr %4, i64 %128
  store i32 %126, ptr %129, align 4
  br label %130

130:                                              ; preds = %125, %104
  %131 = load i32, ptr %89, align 4
  %132 = icmp eq i32 %131, 0
  br i1 %132, label %145, label %133

133:                                              ; preds = %130
  %134 = zext i32 %131 to i64
  br label %135

135:                                              ; preds = %142, %133
  %136 = phi i64 [ %134, %133 ], [ %137, %142 ]
  %137 = add nsw i64 %136, -1
  %138 = and i64 %137, 4294967295
  %139 = getelementptr inbounds nuw i32, ptr %4, i64 %138
  %140 = load i32, ptr %139, align 4
  %141 = icmp eq i32 %140, 0
  br i1 %141, label %142, label %145

142:                                              ; preds = %135
  %143 = trunc i64 %137 to i32
  store i32 %143, ptr %89, align 4
  %144 = icmp eq i32 %143, 0
  br i1 %144, label %145, label %135

145:                                              ; preds = %135, %142, %87, %130
  %146 = load i32, ptr %89, align 4
  %147 = getelementptr inbounds nuw i8, ptr %1, i64 768
  %148 = load i32, ptr %147, align 4
  %149 = icmp eq i32 %146, %148
  br i1 %149, label %150, label %152

150:                                              ; preds = %145
  %151 = zext i32 %146 to i64
  br label %155

152:                                              ; preds = %145
  %153 = icmp ugt i32 %146, %148
  %154 = select i1 %153, i32 1, i32 -1
  br label %168

155:                                              ; preds = %158, %150
  %156 = phi i64 [ %151, %150 ], [ %159, %158 ]
  %157 = icmp eq i64 %156, 0
  br i1 %157, label %168, label %158

158:                                              ; preds = %155
  %159 = add nsw i64 %156, -1
  %160 = getelementptr inbounds nuw i32, ptr %4, i64 %159
  %161 = load i32, ptr %160, align 4
  %162 = getelementptr inbounds nuw i32, ptr %1, i64 %159
  %163 = load i32, ptr %162, align 4
  %164 = icmp eq i32 %161, %163
  br i1 %164, label %155, label %165

165:                                              ; preds = %158
  %166 = icmp ugt i32 %161, %163
  %167 = select i1 %166, i32 1, i32 -1
  br label %168

168:                                              ; preds = %155, %74, %165, %152, %84, %71
  %169 = phi i32 [ 0, %74 ], [ %73, %71 ], [ %86, %84 ], [ %154, %152 ], [ %167, %165 ], [ 0, %155 ]
  call void @llvm.lifetime.end.p0(ptr nonnull %4) #6
  ret i32 %169
}

; Function Attrs: nofree norecurse nosync nounwind sspstrong memory(argmem: readwrite) uwtable
define internal fastcc void @shl(ptr noundef nonnull captures(none) initializes((0, 772)) %0, ptr noundef nonnull readonly captures(none) %1, i32 noundef %2) unnamed_addr #2 {
  %4 = getelementptr inbounds nuw i8, ptr %0, i64 768
  %5 = lshr i32 %2, 5
  %6 = and i32 %2, 31
  %7 = getelementptr inbounds nuw i8, ptr %1, i64 768
  tail call void @llvm.memset.p0.i64(ptr noundef nonnull align 4 dereferenceable(772) %0, i8 0, i64 772, i1 false)
  %8 = load i32, ptr %7, align 4
  %9 = icmp ne i32 %6, 0
  %10 = zext i1 %9 to i32
  %11 = add nuw nsw i32 %5, %10
  %12 = add i32 %11, %8
  %13 = icmp ugt i32 %12, 192
  br i1 %13, label %62, label %14

14:                                               ; preds = %3
  %15 = load i32, ptr %7, align 4
  %16 = icmp eq i32 %15, 0
  br i1 %16, label %19, label %17

17:                                               ; preds = %14
  %18 = zext nneg i32 %6 to i64
  br label %24

19:                                               ; preds = %24, %14
  %20 = phi i64 [ 0, %14 ], [ %37, %24 ]
  %21 = phi i32 [ 0, %14 ], [ %39, %24 ]
  %22 = add i32 %21, %5
  store i32 %22, ptr %4, align 4
  %23 = icmp eq i64 %20, 0
  br i1 %23, label %47, label %42

24:                                               ; preds = %17, %24
  %25 = phi i64 [ 0, %17 ], [ %38, %24 ]
  %26 = phi i64 [ 0, %17 ], [ %37, %24 ]
  %27 = getelementptr inbounds nuw i32, ptr %1, i64 %25
  %28 = load i32, ptr %27, align 4
  %29 = zext i32 %28 to i64
  %30 = shl nuw nsw i64 %29, %18
  %31 = or i64 %30, %26
  %32 = trunc i64 %31 to i32
  %33 = trunc nuw i64 %25 to i32
  %34 = add i32 %5, %33
  %35 = zext i32 %34 to i64
  %36 = getelementptr inbounds nuw i32, ptr %0, i64 %35
  store i32 %32, ptr %36, align 4
  %37 = lshr i64 %30, 32
  %38 = add nuw nsw i64 %25, 1
  %39 = load i32, ptr %7, align 4
  %40 = zext i32 %39 to i64
  %41 = icmp samesign ult i64 %38, %40
  br i1 %41, label %24, label %19

42:                                               ; preds = %19
  %43 = trunc nuw nsw i64 %20 to i32
  %44 = add i32 %22, 1
  store i32 %44, ptr %4, align 4
  %45 = zext i32 %22 to i64
  %46 = getelementptr inbounds nuw i32, ptr %0, i64 %45
  store i32 %43, ptr %46, align 4
  br label %47

47:                                               ; preds = %42, %19
  %48 = load i32, ptr %4, align 4
  %49 = icmp eq i32 %48, 0
  br i1 %49, label %62, label %50

50:                                               ; preds = %47
  %51 = zext i32 %48 to i64
  br label %52

52:                                               ; preds = %59, %50
  %53 = phi i64 [ %51, %50 ], [ %54, %59 ]
  %54 = add nsw i64 %53, -1
  %55 = and i64 %54, 4294967295
  %56 = getelementptr inbounds nuw i32, ptr %0, i64 %55
  %57 = load i32, ptr %56, align 4
  %58 = icmp eq i32 %57, 0
  br i1 %58, label %59, label %62

59:                                               ; preds = %52
  %60 = trunc i64 %54 to i32
  store i32 %60, ptr %4, align 4
  %61 = icmp eq i32 %60, 0
  br i1 %61, label %62, label %52

62:                                               ; preds = %59, %52, %47, %3
  ret void
}

; Function Attrs: mustprogress nocallback nofree nounwind willreturn memory(argmem: readwrite)

; Function Attrs: nofree norecurse nosync nounwind sspstrong memory(argmem: readwrite) uwtable
define internal fastcc i64 @quotient(ptr noundef nonnull captures(none) %0, ptr noundef nonnull readonly captures(none) %1) unnamed_addr #2 {
  %3 = alloca %struct.Big, align 4
  %4 = getelementptr inbounds nuw i8, ptr %0, i64 768
  %5 = load i32, ptr %4, align 4
  %6 = icmp eq i32 %5, 0
  br i1 %6, label %28, label %7

7:                                                ; preds = %2
  %8 = add i32 %5, -1
  %9 = shl i32 %8, 5
  %10 = add i32 %9, 32
  %11 = zext i32 %8 to i64
  %12 = getelementptr inbounds nuw i32, ptr %0, i64 %11
  %13 = load i32, ptr %12, align 4
  %14 = icmp eq i32 %13, 0
  br i1 %14, label %25, label %15

15:                                               ; preds = %7
  %16 = icmp sgt i32 %13, -1
  br i1 %16, label %17, label %25

17:                                               ; preds = %15, %17
  %18 = phi i32 [ %21, %17 ], [ 0, %15 ]
  %19 = phi i32 [ %20, %17 ], [ %13, %15 ]
  %20 = shl nuw i32 %19, 1
  %21 = add i32 %18, 1
  %22 = icmp sgt i32 %20, -1
  br i1 %22, label %17, label %23

23:                                               ; preds = %17
  %24 = xor i32 %18, -1
  br label %25

25:                                               ; preds = %23, %15, %7
  %26 = phi i32 [ -32, %7 ], [ 0, %15 ], [ %24, %23 ]
  %27 = add i32 %10, %26
  br label %28

28:                                               ; preds = %2, %25
  %29 = phi i32 [ %27, %25 ], [ 0, %2 ]
  %30 = getelementptr inbounds nuw i8, ptr %1, i64 768
  %31 = load i32, ptr %30, align 4
  %32 = icmp eq i32 %31, 0
  br i1 %32, label %54, label %33

33:                                               ; preds = %28
  %34 = add i32 %31, -1
  %35 = shl i32 %34, 5
  %36 = add i32 %35, 32
  %37 = zext i32 %34 to i64
  %38 = getelementptr inbounds nuw i32, ptr %1, i64 %37
  %39 = load i32, ptr %38, align 4
  %40 = icmp eq i32 %39, 0
  br i1 %40, label %51, label %41

41:                                               ; preds = %33
  %42 = icmp sgt i32 %39, -1
  br i1 %42, label %43, label %51

43:                                               ; preds = %41, %43
  %44 = phi i32 [ %47, %43 ], [ 0, %41 ]
  %45 = phi i32 [ %46, %43 ], [ %39, %41 ]
  %46 = shl nuw i32 %45, 1
  %47 = add i32 %44, 1
  %48 = icmp sgt i32 %46, -1
  br i1 %48, label %43, label %49

49:                                               ; preds = %43
  %50 = xor i32 %44, -1
  br label %51

51:                                               ; preds = %49, %41, %33
  %52 = phi i32 [ -32, %33 ], [ 0, %41 ], [ %50, %49 ]
  %53 = add i32 %36, %52
  br label %54

54:                                               ; preds = %28, %51
  %55 = phi i32 [ %53, %51 ], [ 0, %28 ]
  %56 = sub nsw i32 %29, %55
  %57 = icmp sgt i32 %56, -1
  br i1 %57, label %58, label %61

58:                                               ; preds = %54
  %59 = getelementptr inbounds nuw i8, ptr %3, i64 768
  %60 = zext nneg i32 %56 to i64
  br label %63

61:                                               ; preds = %189, %54
  %62 = phi i64 [ 0, %54 ], [ %190, %189 ]
  ret i64 %62

63:                                               ; preds = %58, %189
  %64 = phi i64 [ %60, %58 ], [ %191, %189 ]
  %65 = phi i64 [ 0, %58 ], [ %190, %189 ]
  call void @llvm.lifetime.start.p0(ptr nonnull %3) #6
  %66 = trunc nuw nsw i64 %64 to i32
  %67 = lshr i32 %66, 5
  call void @llvm.memset.p0.i64(ptr noundef nonnull align 4 dereferenceable(772) %3, i8 0, i64 772, i1 false)
  %68 = load i32, ptr %30, align 4
  %69 = and i64 %64, 31
  %70 = icmp ne i64 %69, 0
  %71 = zext i1 %70 to i32
  %72 = add nuw nsw i32 %67, %71
  %73 = add i32 %72, %68
  %74 = icmp ugt i32 %73, 192
  br i1 %74, label %121, label %75

75:                                               ; preds = %63
  %76 = icmp eq i32 %68, 0
  br i1 %76, label %80, label %77

77:                                               ; preds = %75
  %78 = and i64 %64, 31
  %79 = zext i32 %68 to i64
  br label %85

80:                                               ; preds = %85, %75
  %81 = phi i64 [ 0, %75 ], [ %98, %85 ]
  %82 = phi i32 [ 0, %75 ], [ %68, %85 ]
  %83 = add i32 %82, %67
  store i32 %83, ptr %59, align 4
  %84 = icmp eq i64 %81, 0
  br i1 %84, label %106, label %101

85:                                               ; preds = %85, %77
  %86 = phi i64 [ 0, %77 ], [ %99, %85 ]
  %87 = phi i64 [ 0, %77 ], [ %98, %85 ]
  %88 = getelementptr inbounds nuw i32, ptr %1, i64 %86
  %89 = load i32, ptr %88, align 4
  %90 = zext i32 %89 to i64
  %91 = shl nuw nsw i64 %90, %78
  %92 = or i64 %91, %87
  %93 = trunc i64 %92 to i32
  %94 = trunc nuw i64 %86 to i32
  %95 = add i32 %67, %94
  %96 = zext i32 %95 to i64
  %97 = getelementptr inbounds nuw i32, ptr %3, i64 %96
  store i32 %93, ptr %97, align 4
  %98 = lshr i64 %91, 32
  %99 = add nuw nsw i64 %86, 1
  %100 = icmp eq i64 %99, %79
  br i1 %100, label %80, label %85

101:                                              ; preds = %80
  %102 = trunc nuw nsw i64 %81 to i32
  %103 = add i32 %83, 1
  store i32 %103, ptr %59, align 4
  %104 = zext i32 %83 to i64
  %105 = getelementptr inbounds nuw i32, ptr %3, i64 %104
  store i32 %102, ptr %105, align 4
  br label %106

106:                                              ; preds = %101, %80
  %107 = load i32, ptr %59, align 4
  %108 = icmp eq i32 %107, 0
  br i1 %108, label %121, label %109

109:                                              ; preds = %106
  %110 = zext i32 %107 to i64
  br label %111

111:                                              ; preds = %118, %109
  %112 = phi i64 [ %110, %109 ], [ %113, %118 ]
  %113 = add nsw i64 %112, -1
  %114 = and i64 %113, 4294967295
  %115 = getelementptr inbounds nuw i32, ptr %3, i64 %114
  %116 = load i32, ptr %115, align 4
  %117 = icmp eq i32 %116, 0
  br i1 %117, label %118, label %121

118:                                              ; preds = %111
  %119 = trunc i64 %113 to i32
  store i32 %119, ptr %59, align 4
  %120 = icmp eq i32 %119, 0
  br i1 %120, label %121, label %111

121:                                              ; preds = %111, %118, %63, %106
  %122 = load i32, ptr %4, align 4
  %123 = load i32, ptr %59, align 4
  %124 = icmp eq i32 %122, %123
  br i1 %124, label %125, label %127

125:                                              ; preds = %121
  %126 = zext i32 %122 to i64
  br label %129

127:                                              ; preds = %121
  %128 = icmp ugt i32 %122, %123
  br label %141

129:                                              ; preds = %132, %125
  %130 = phi i64 [ %126, %125 ], [ %133, %132 ]
  %131 = icmp eq i64 %130, 0
  br i1 %131, label %143, label %132

132:                                              ; preds = %129
  %133 = add nsw i64 %130, -1
  %134 = getelementptr inbounds nuw i32, ptr %0, i64 %133
  %135 = load i32, ptr %134, align 4
  %136 = getelementptr inbounds nuw i32, ptr %3, i64 %133
  %137 = load i32, ptr %136, align 4
  %138 = icmp eq i32 %135, %137
  br i1 %138, label %129, label %139

139:                                              ; preds = %132
  %140 = icmp ugt i32 %135, %137
  br label %141

141:                                              ; preds = %127, %139
  %142 = phi i1 [ %128, %127 ], [ %140, %139 ]
  br i1 %142, label %143, label %189

143:                                              ; preds = %129, %141
  %144 = icmp eq i32 %122, 0
  br i1 %144, label %147, label %145

145:                                              ; preds = %143
  %146 = zext i32 %123 to i64
  br label %162

147:                                              ; preds = %173, %143
  %148 = phi i32 [ 0, %143 ], [ %181, %173 ]
  %149 = icmp eq i32 %148, 0
  br i1 %149, label %184, label %150

150:                                              ; preds = %147
  %151 = zext i32 %148 to i64
  br label %152

152:                                              ; preds = %159, %150
  %153 = phi i64 [ %151, %150 ], [ %154, %159 ]
  %154 = add nsw i64 %153, -1
  %155 = and i64 %154, 4294967295
  %156 = getelementptr inbounds nuw i32, ptr %0, i64 %155
  %157 = load i32, ptr %156, align 4
  %158 = icmp eq i32 %157, 0
  br i1 %158, label %159, label %184

159:                                              ; preds = %152
  %160 = trunc i64 %154 to i32
  store i32 %160, ptr %4, align 4
  %161 = icmp eq i32 %160, 0
  br i1 %161, label %184, label %152

162:                                              ; preds = %145, %173
  %163 = phi i64 [ %180, %173 ], [ 0, %145 ]
  %164 = phi i64 [ %179, %173 ], [ 0, %145 ]
  %165 = getelementptr inbounds nuw i32, ptr %0, i64 %163
  %166 = load i32, ptr %165, align 4
  %167 = zext i32 %166 to i64
  %168 = icmp samesign ult i64 %163, %146
  br i1 %168, label %169, label %173

169:                                              ; preds = %162
  %170 = getelementptr inbounds nuw i32, ptr %3, i64 %163
  %171 = load i32, ptr %170, align 4
  %172 = zext i32 %171 to i64
  br label %173

173:                                              ; preds = %169, %162
  %174 = phi i64 [ %172, %169 ], [ 0, %162 ]
  %175 = add nuw nsw i64 %174, %164
  %176 = trunc i64 %175 to i32
  %177 = sub i32 %166, %176
  store i32 %177, ptr %165, align 4
  %178 = icmp samesign ugt i64 %175, %167
  %179 = zext i1 %178 to i64
  %180 = add nuw nsw i64 %163, 1
  %181 = load i32, ptr %4, align 4
  %182 = zext i32 %181 to i64
  %183 = icmp samesign ult i64 %180, %182
  br i1 %183, label %162, label %147

184:                                              ; preds = %152, %159, %147
  %185 = icmp slt i64 %64, 64
  br i1 %185, label %186, label %189

186:                                              ; preds = %184
  %187 = shl nuw i64 1, %64
  %188 = or i64 %187, %65
  br label %189

189:                                              ; preds = %184, %186, %141
  %190 = phi i64 [ %188, %186 ], [ %65, %184 ], [ %65, %141 ]
  call void @llvm.lifetime.end.p0(ptr nonnull %3) #6
  %191 = add nsw i64 %64, -1
  %192 = icmp sgt i64 %64, 0
  br i1 %192, label %63, label %61
}

; Function Attrs: nocallback nocreateundeforpoison nofree nosync nounwind speculatable willreturn memory(none)
declare i32 @llvm.usub.sat.i32(i32, i32) #4

; Function Attrs: nocallback nocreateundeforpoison nofree nosync nounwind speculatable willreturn memory(none)
declare i64 @llvm.smin.i64(i64, i64) #4

; Function Attrs: nocallback nofree nounwind willreturn memory(argmem: write)
declare void @llvm.memset.p0.i64(ptr writeonly captures(none), i8, i64, i1 immarg) #5

; Function Attrs: nocallback nocreateundeforpoison nofree nosync nounwind speculatable willreturn memory(none)
declare i32 @llvm.umin.i32(i32, i32) #4

attributes #0 = { nofree norecurse nosync nounwind sspstrong memory(argmem: read) uwtable "min-legal-vector-width"="0" "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-cpu"="x86-64" "target-features"="+cmov,+cx8,+fxsr,+mmx,+sse,+sse2,+x87" "tune-cpu"="generic" }
attributes #1 = { mustprogress nocallback nofree nosync nounwind willreturn memory(argmem: readwrite) }
attributes #2 = { nofree norecurse nosync nounwind sspstrong memory(argmem: readwrite) uwtable "min-legal-vector-width"="0" "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-cpu"="x86-64" "target-features"="+cmov,+cx8,+fxsr,+mmx,+sse,+sse2,+x87" "tune-cpu"="generic" }
attributes #3 = { mustprogress nocallback nofree nounwind willreturn memory(argmem: readwrite) }
attributes #4 = { nocallback nocreateundeforpoison nofree nosync nounwind speculatable willreturn memory(none) }
attributes #5 = { nocallback nofree nounwind willreturn memory(argmem: write) }
attributes #6 = { nounwind }

