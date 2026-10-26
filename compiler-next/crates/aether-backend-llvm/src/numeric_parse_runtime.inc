%struct.Big = type { [192 x i32], i32 }

; Function Attrs: nofree norecurse nosync nounwind memory(argmem: read) uwtable
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
  %15 = phi i64 [ %13, %11 ], [ 0, %2 ], [ 0, %9 ]
  %16 = phi i64 [ 1, %11 ], [ 0, %2 ], [ 0, %9 ]
  call void @llvm.lifetime.start.p0(i64 772, ptr nonnull %3) #6
  %17 = getelementptr inbounds nuw i8, ptr %3, i64 768
  %18 = icmp ult i64 %16, %1
  call void @llvm.memset.p0.i64(ptr noundef nonnull align 4 dereferenceable(772) %3, i8 0, i64 772, i1 false)
  br i1 %18, label %19, label %136

19:                                               ; preds = %14, %128
  %20 = phi i64 [ %129, %128 ], [ %16, %14 ]
  %21 = phi i32 [ %127, %128 ], [ 0, %14 ]
  %22 = phi i32 [ %126, %128 ], [ 0, %14 ]
  %23 = phi i32 [ %125, %128 ], [ 0, %14 ]
  %24 = phi i64 [ %124, %128 ], [ 0, %14 ]
  %25 = phi i64 [ %123, %128 ], [ 0, %14 ]
  %26 = phi i64 [ %121, %128 ], [ 0, %14 ]
  %27 = phi i32 [ %120, %128 ], [ 0, %14 ]
  %28 = getelementptr inbounds nuw i8, ptr %0, i64 %20
  %29 = load i8, ptr %28, align 1
  %30 = add i8 %29, -48
  %31 = icmp ult i8 %30, 10
  %32 = icmp ne i32 %23, 0
  br i1 %31, label %33, label %108

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
  br i1 %42, label %43, label %103

43:                                               ; preds = %33
  %44 = icmp ult i64 %25, 780
  br i1 %44, label %45, label %100

45:                                               ; preds = %43
  %46 = load i32, ptr %17, align 4
  %47 = icmp eq i32 %46, 0
  br i1 %47, label %48, label %54

48:                                               ; preds = %54, %45
  %49 = phi i64 [ 0, %45 ], [ %63, %54 ]
  %50 = phi i32 [ %46, %45 ], [ %65, %54 ]
  %51 = icmp ne i64 %49, 0
  %52 = icmp ult i32 %50, 192
  %53 = and i1 %51, %52
  br i1 %53, label %68, label %73

54:                                               ; preds = %45, %54
  %55 = phi i64 [ %64, %54 ], [ 0, %45 ]
  %56 = phi i64 [ %63, %54 ], [ 0, %45 ]
  %57 = getelementptr inbounds nuw [192 x i32], ptr %3, i64 0, i64 %55
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
  %72 = getelementptr inbounds nuw [192 x i32], ptr %3, i64 0, i64 %71
  store i32 %69, ptr %72, align 4
  br label %73

73:                                               ; preds = %48, %68
  br i1 %41, label %74, label %98

74:                                               ; preds = %73
  %75 = zext nneg i32 %39 to i64
  br label %76

76:                                               ; preds = %82, %74
  %77 = phi i64 [ %89, %82 ], [ 0, %74 ]
  %78 = phi i64 [ %88, %82 ], [ %75, %74 ]
  %79 = load i32, ptr %17, align 4
  %80 = zext i32 %79 to i64
  %81 = icmp samesign ult i64 %77, %80
  br i1 %81, label %82, label %91

82:                                               ; preds = %76
  %83 = getelementptr inbounds nuw [192 x i32], ptr %3, i64 0, i64 %77
  %84 = load i32, ptr %83, align 4
  %85 = zext i32 %84 to i64
  %86 = add nuw nsw i64 %78, %85
  %87 = trunc i64 %86 to i32
  store i32 %87, ptr %83, align 4
  %88 = lshr i64 %86, 32
  %89 = add nuw nsw i64 %77, 1
  %90 = icmp samesign ult i64 %86, 4294967296
  br i1 %90, label %98, label %76

91:                                               ; preds = %76
  %92 = icmp ult i32 %79, 192
  br i1 %92, label %93, label %98

93:                                               ; preds = %91
  %94 = trunc nuw nsw i64 %78 to i32
  %95 = add nuw nsw i32 %79, 1
  store i32 %95, ptr %17, align 4
  %96 = zext nneg i32 %79 to i64
  %97 = getelementptr inbounds nuw [192 x i32], ptr %3, i64 0, i64 %96
  store i32 %94, ptr %97, align 4
  br label %98

98:                                               ; preds = %82, %73, %91, %93
  %99 = add nuw nsw i64 %25, 1
  br label %103

100:                                              ; preds = %43
  %101 = add i64 %26, 1
  %102 = select i1 %41, i32 1, i32 %27
  br label %103

103:                                              ; preds = %100, %33, %98
  %104 = phi i32 [ %27, %98 ], [ %102, %100 ], [ %27, %33 ]
  %105 = phi i64 [ %26, %98 ], [ %101, %100 ], [ %26, %33 ]
  %106 = phi i64 [ %99, %98 ], [ %25, %100 ], [ %25, %33 ]
  %107 = phi i32 [ 1, %98 ], [ 1, %100 ], [ 0, %33 ]
  br i1 %42, label %111, label %119

108:                                              ; preds = %19
  %109 = icmp ne i8 %29, 46
  %110 = select i1 %109, i1 true, i1 %32
  br i1 %110, label %119, label %111

111:                                              ; preds = %108, %103
  %112 = phi i32 [ %104, %103 ], [ %27, %108 ]
  %113 = phi i64 [ %105, %103 ], [ %26, %108 ]
  %114 = phi i64 [ %106, %103 ], [ %25, %108 ]
  %115 = phi i64 [ %38, %103 ], [ %24, %108 ]
  %116 = phi i32 [ %23, %103 ], [ 1, %108 ]
  %117 = phi i32 [ %107, %103 ], [ %22, %108 ]
  %118 = phi i32 [ 1, %103 ], [ %21, %108 ]
  br label %119

119:                                              ; preds = %108, %103, %111
  %120 = phi i32 [ %112, %111 ], [ %104, %103 ], [ %27, %108 ]
  %121 = phi i64 [ %113, %111 ], [ %105, %103 ], [ %26, %108 ]
  %122 = phi i1 [ false, %111 ], [ false, %103 ], [ true, %108 ]
  %123 = phi i64 [ %114, %111 ], [ %106, %103 ], [ %25, %108 ]
  %124 = phi i64 [ %115, %111 ], [ %38, %103 ], [ %24, %108 ]
  %125 = phi i32 [ %116, %111 ], [ %23, %103 ], [ %23, %108 ]
  %126 = phi i32 [ %117, %111 ], [ %107, %103 ], [ %22, %108 ]
  %127 = phi i32 [ %118, %111 ], [ 1, %103 ], [ %21, %108 ]
  br i1 %122, label %131, label %128

128:                                              ; preds = %119
  %129 = add nuw i64 %20, 1
  %130 = icmp eq i64 %129, %1
  br i1 %130, label %131, label %19

131:                                              ; preds = %119, %128
  %132 = phi i64 [ %20, %119 ], [ %1, %128 ]
  %133 = icmp eq i32 %127, 0
  %134 = icmp eq i32 %126, 0
  %135 = icmp eq i32 %120, 0
  br label %136

136:                                              ; preds = %131, %14
  %137 = phi i64 [ %16, %14 ], [ %132, %131 ]
  %138 = phi i1 [ false, %14 ], [ %122, %131 ]
  %139 = phi i1 [ true, %14 ], [ %135, %131 ]
  %140 = phi i64 [ 0, %14 ], [ %121, %131 ]
  %141 = phi i64 [ 0, %14 ], [ %123, %131 ]
  %142 = phi i64 [ 0, %14 ], [ %124, %131 ]
  %143 = phi i1 [ true, %14 ], [ %134, %131 ]
  %144 = phi i1 [ true, %14 ], [ %133, %131 ]
  br i1 %144, label %506, label %145

145:                                              ; preds = %136
  br i1 %138, label %146, label %193

146:                                              ; preds = %145
  %147 = getelementptr inbounds nuw i8, ptr %0, i64 %137
  %148 = load i8, ptr %147, align 1
  switch i8 %148, label %193 [
    i8 101, label %149
    i8 69, label %149
  ]

149:                                              ; preds = %146, %146
  %150 = add i64 %137, 1
  %151 = icmp ult i64 %150, %1
  br i1 %151, label %152, label %159

152:                                              ; preds = %149
  %153 = getelementptr inbounds nuw i8, ptr %0, i64 %150
  %154 = load i8, ptr %153, align 1
  switch i8 %154, label %159 [
    i8 43, label %155
    i8 45, label %155
  ]

155:                                              ; preds = %152, %152
  %156 = icmp eq i8 %154, 45
  %157 = zext i1 %156 to i32
  %158 = add i64 %137, 2
  br label %159

159:                                              ; preds = %152, %155, %149
  %160 = phi i32 [ %157, %155 ], [ 0, %149 ], [ 0, %152 ]
  %161 = phi i64 [ %158, %155 ], [ %150, %149 ], [ %150, %152 ]
  %162 = icmp ult i64 %161, %1
  br i1 %162, label %163, label %189

163:                                              ; preds = %159
  %164 = getelementptr inbounds nuw i8, ptr %0, i64 %161
  %165 = load i8, ptr %164, align 1
  %166 = add i8 %165, -58
  %167 = icmp ult i8 %166, -10
  br i1 %167, label %189, label %173

168:                                              ; preds = %184
  %169 = getelementptr inbounds nuw i8, ptr %0, i64 %186
  %170 = load i8, ptr %169, align 1
  %171 = add i8 %170, -48
  %172 = icmp ult i8 %171, 10
  br i1 %172, label %173, label %189

173:                                              ; preds = %163, %168
  %174 = phi i8 [ %170, %168 ], [ %165, %163 ]
  %175 = phi i64 [ %185, %168 ], [ 0, %163 ]
  %176 = phi i64 [ %186, %168 ], [ %161, %163 ]
  %177 = icmp slt i64 %175, 1000000
  br i1 %177, label %178, label %184

178:                                              ; preds = %173
  %179 = mul nsw i64 %175, 10
  %180 = and i8 %174, 15
  %181 = zext nneg i8 %180 to i64
  %182 = add nsw i64 %179, %181
  %183 = tail call i64 @llvm.smin.i64(i64 %182, i64 1000000)
  br label %184

184:                                              ; preds = %173, %178
  %185 = phi i64 [ %183, %178 ], [ %175, %173 ]
  %186 = add nuw i64 %176, 1
  %187 = icmp eq i64 %186, %1
  br i1 %187, label %188, label %168

188:                                              ; preds = %184
  br label %189

189:                                              ; preds = %168, %163, %188, %159
  %190 = phi i64 [ 0, %159 ], [ %185, %188 ], [ 0, %163 ], [ %185, %168 ]
  %191 = phi i1 [ true, %159 ], [ false, %188 ], [ true, %163 ], [ false, %168 ]
  %192 = phi i64 [ %161, %159 ], [ %1, %188 ], [ %161, %163 ], [ %186, %168 ]
  br i1 %191, label %501, label %193

193:                                              ; preds = %146, %189, %145
  %194 = phi i64 [ %190, %189 ], [ 0, %145 ], [ 0, %146 ]
  %195 = phi i32 [ %160, %189 ], [ 0, %145 ], [ 0, %146 ]
  %196 = phi i64 [ %192, %189 ], [ %137, %145 ], [ %137, %146 ]
  %197 = icmp eq i64 %196, %1
  br i1 %197, label %198, label %501

198:                                              ; preds = %193
  br i1 %143, label %199, label %201

199:                                              ; preds = %198
  %200 = insertvalue { i32, i64 } { i32 0, i64 poison }, i64 %15, 1
  br label %497

201:                                              ; preds = %198
  %202 = icmp eq i32 %195, 0
  %203 = sub nsw i64 0, %194
  %204 = select i1 %202, i64 %194, i64 %203
  %205 = icmp slt i64 %142, 0
  %206 = add nsw i64 %142, 1000000
  %207 = icmp sgt i64 %204, %206
  %208 = select i1 %205, i1 %207, i1 false
  br i1 %208, label %216, label %209

209:                                              ; preds = %201
  %210 = icmp sgt i64 %142, 0
  %211 = add nsw i64 %142, -1000000
  %212 = icmp slt i64 %204, %211
  %213 = select i1 %210, i1 %212, i1 false
  %214 = sub nsw i64 %204, %142
  %215 = select i1 %213, i64 -1000000, i64 %214
  br label %216

216:                                              ; preds = %201, %209
  %217 = phi i64 [ 1000000, %201 ], [ %215, %209 ]
  %218 = icmp sgt i64 %140, 0
  %219 = sub nsw i64 1000000, %140
  %220 = icmp sgt i64 %217, %219
  %221 = select i1 %218, i1 %220, i1 false
  br i1 %221, label %229, label %222

222:                                              ; preds = %216
  %223 = icmp slt i64 %140, 0
  %224 = sub nsw i64 -1000000, %140
  %225 = icmp slt i64 %217, %224
  %226 = select i1 %223, i1 %225, i1 false
  %227 = add nsw i64 %217, %140
  %228 = select i1 %226, i64 -1000000, i64 %227
  br label %229

229:                                              ; preds = %216, %222
  %230 = phi i64 [ 1000000, %216 ], [ %228, %222 ]
  %231 = icmp sgt i64 %230, 1
  %232 = sub nsw i64 1000001, %230
  %233 = icmp sgt i64 %141, %232
  %234 = select i1 %231, i1 %233, i1 false
  br i1 %234, label %243, label %235

235:                                              ; preds = %229
  %236 = icmp slt i64 %230, 1
  %237 = sub nsw i64 -999999, %230
  %238 = icmp slt i64 %141, %237
  %239 = select i1 %236, i1 %238, i1 false
  %240 = add i64 %141, -1
  %241 = add i64 %240, %230
  %242 = select i1 %239, i64 -1000000, i64 %241
  br label %243

243:                                              ; preds = %229, %235
  %244 = phi i64 [ 1000000, %229 ], [ %242, %235 ]
  %245 = icmp sgt i64 %244, 309
  br i1 %245, label %497, label %246

246:                                              ; preds = %243
  %247 = icmp slt i64 %244, -324
  br i1 %247, label %497, label %248

248:                                              ; preds = %246
  %249 = icmp sgt i64 %230, -1
  br i1 %249, label %250, label %376

250:                                              ; preds = %248
  %251 = icmp eq i64 %230, 0
  br i1 %251, label %252, label %280

252:                                              ; preds = %309, %250
  %253 = load i32, ptr %17, align 4
  %254 = icmp eq i32 %253, 0
  br i1 %254, label %276, label %255

255:                                              ; preds = %252
  %256 = add i32 %253, -1
  %257 = shl i32 %256, 5
  %258 = add i32 %257, 32
  %259 = zext i32 %256 to i64
  %260 = getelementptr inbounds nuw [192 x i32], ptr %3, i64 0, i64 %259
  %261 = load i32, ptr %260, align 4
  %262 = icmp eq i32 %261, 0
  br i1 %262, label %273, label %263

263:                                              ; preds = %255
  %264 = icmp sgt i32 %261, -1
  br i1 %264, label %265, label %273

265:                                              ; preds = %263, %265
  %266 = phi i32 [ %269, %265 ], [ 0, %263 ]
  %267 = phi i32 [ %268, %265 ], [ %261, %263 ]
  %268 = shl nuw i32 %267, 1
  %269 = add i32 %266, 1
  %270 = icmp sgt i32 %268, -1
  br i1 %270, label %265, label %271

271:                                              ; preds = %265
  %272 = xor i32 %266, -1
  br label %273

273:                                              ; preds = %271, %263, %255
  %274 = phi i32 [ -32, %255 ], [ 0, %263 ], [ %272, %271 ]
  %275 = add i32 %258, %274
  br label %276

276:                                              ; preds = %252, %273
  %277 = phi i32 [ %275, %273 ], [ 0, %252 ]
  %278 = tail call i32 @llvm.usub.sat.i32(i32 %277, i32 53)
  %279 = icmp ult i32 %277, 54
  br i1 %279, label %334, label %312

280:                                              ; preds = %250, %309
  %281 = phi i64 [ %310, %309 ], [ 0, %250 ]
  %282 = load i32, ptr %17, align 4
  %283 = icmp eq i32 %282, 0
  br i1 %283, label %284, label %290

284:                                              ; preds = %290, %280
  %285 = phi i64 [ 0, %280 ], [ %299, %290 ]
  %286 = phi i32 [ %282, %280 ], [ %301, %290 ]
  %287 = icmp ne i64 %285, 0
  %288 = icmp ult i32 %286, 192
  %289 = and i1 %287, %288
  br i1 %289, label %304, label %309

290:                                              ; preds = %280, %290
  %291 = phi i64 [ %300, %290 ], [ 0, %280 ]
  %292 = phi i64 [ %299, %290 ], [ 0, %280 ]
  %293 = getelementptr inbounds nuw [192 x i32], ptr %3, i64 0, i64 %291
  %294 = load i32, ptr %293, align 4
  %295 = zext i32 %294 to i64
  %296 = mul nuw nsw i64 %295, 5
  %297 = add nuw nsw i64 %296, %292
  %298 = trunc i64 %297 to i32
  store i32 %298, ptr %293, align 4
  %299 = lshr i64 %297, 32
  %300 = add nuw nsw i64 %291, 1
  %301 = load i32, ptr %17, align 4
  %302 = zext i32 %301 to i64
  %303 = icmp samesign ult i64 %300, %302
  br i1 %303, label %290, label %284

304:                                              ; preds = %284
  %305 = trunc nuw nsw i64 %285 to i32
  %306 = add nuw nsw i32 %286, 1
  store i32 %306, ptr %17, align 4
  %307 = zext nneg i32 %286 to i64
  %308 = getelementptr inbounds nuw [192 x i32], ptr %3, i64 0, i64 %307
  store i32 %305, ptr %308, align 4
  br label %309

309:                                              ; preds = %284, %304
  %310 = add nuw nsw i64 %281, 1
  %311 = icmp eq i64 %310, %230
  br i1 %311, label %252, label %280

312:                                              ; preds = %276, %327
  %313 = phi i64 [ %332, %327 ], [ 0, %276 ]
  %314 = phi i64 [ %331, %327 ], [ 0, %276 ]
  %315 = trunc nuw nsw i64 %313 to i32
  %316 = add i32 %278, %315
  %317 = lshr i32 %316, 5
  %318 = icmp ult i32 %317, %253
  br i1 %318, label %319, label %327

319:                                              ; preds = %312
  %320 = zext nneg i32 %317 to i64
  %321 = getelementptr inbounds nuw [192 x i32], ptr %3, i64 0, i64 %320
  %322 = load i32, ptr %321, align 4
  %323 = and i32 %316, 31
  %324 = shl nuw i32 1, %323
  %325 = and i32 %322, %324
  %326 = icmp eq i32 %325, 0
  br label %327

327:                                              ; preds = %319, %312
  %328 = phi i1 [ %326, %319 ], [ true, %312 ]
  %329 = shl nuw nsw i64 1, %313
  %330 = select i1 %328, i64 0, i64 %329
  %331 = or i64 %330, %314
  %332 = add nuw nsw i64 %313, 1
  %333 = icmp eq i64 %332, 53
  br i1 %333, label %348, label %312

334:                                              ; preds = %276
  %335 = load i32, ptr %3, align 4
  %336 = select i1 %254, i32 0, i32 %335
  %337 = zext i32 %336 to i64
  %338 = icmp ugt i32 %253, 1
  %339 = getelementptr inbounds nuw i8, ptr %3, i64 4
  %340 = load i32, ptr %339, align 4
  %341 = zext i32 %340 to i64
  %342 = shl nuw i64 %341, 32
  %343 = select i1 %338, i64 %342, i64 0
  %344 = or disjoint i64 %343, %337
  %345 = sub nuw nsw i32 53, %277
  %346 = zext nneg i32 %345 to i64
  %347 = shl i64 %344, %346
  br label %348

348:                                              ; preds = %327, %334
  %349 = phi i64 [ %347, %334 ], [ %331, %327 ]
  br i1 %279, label %361, label %350

350:                                              ; preds = %348
  %351 = call fastcc i32 @low_half_cmp(ptr noundef %3, i32 noundef %278)
  %352 = icmp sgt i32 %351, 0
  br i1 %352, label %359, label %353

353:                                              ; preds = %350
  %354 = icmp eq i32 %351, 0
  br i1 %354, label %355, label %361

355:                                              ; preds = %353
  %356 = and i64 %349, 1
  %357 = icmp eq i64 %356, 0
  %358 = select i1 %139, i1 %357, i1 false
  br i1 %358, label %361, label %359

359:                                              ; preds = %355, %350
  %360 = add i64 %349, 1
  br label %361

361:                                              ; preds = %353, %359, %355, %348
  %362 = phi i64 [ %349, %348 ], [ %360, %359 ], [ %349, %353 ], [ %349, %355 ]
  %363 = zext i32 %277 to i64
  %364 = icmp ne i64 %362, 9007199254740992
  %365 = sext i1 %364 to i64
  %366 = add nuw i64 %230, %363
  %367 = add i64 %366, %365
  %368 = icmp sgt i64 %367, 1023
  br i1 %368, label %497, label %369

369:                                              ; preds = %361
  %370 = shl i64 %367, 52
  %371 = add i64 %370, 4607182418800017408
  %372 = and i64 %362, 4503599627370495
  %373 = or disjoint i64 %371, %372
  %374 = or i64 %373, %15
  %375 = insertvalue { i32, i64 } { i32 0, i64 poison }, i64 %374, 1
  br label %497

376:                                              ; preds = %248
  %377 = trunc i64 %230 to i32
  %378 = sub i32 0, %377
  call void @llvm.lifetime.start.p0(i64 772, ptr nonnull %4) #6
  call void @llvm.memset.p0.i64(ptr noundef nonnull align 4 dereferenceable(768) %4, i8 0, i64 768, i1 false)
  %379 = getelementptr inbounds nuw i8, ptr %4, i64 768
  store i32 1, ptr %379, align 4
  store i32 1, ptr %4, align 4
  %380 = icmp eq i32 %377, 0
  br i1 %380, label %381, label %398

381:                                              ; preds = %427, %376
  %382 = call fastcc i32 @bits(ptr noundef %3)
  %383 = zext i32 %382 to i64
  %384 = call fastcc i32 @bits(ptr noundef %4)
  %385 = zext i32 %384 to i64
  %386 = sub nsw i64 %383, %385
  %387 = call fastcc i32 @cmp_shift(ptr noundef %3, ptr noundef %4, i64 noundef %386)
  %388 = ashr i32 %387, 31
  %389 = sext i32 %388 to i64
  %390 = add nsw i64 %386, %389
  %391 = zext i32 %378 to i64
  %392 = sub nsw i64 %390, %391
  %393 = icmp sgt i64 %392, -1023
  %394 = sub nsw i64 52, %390
  %395 = sub nsw i64 1074, %391
  %396 = select i1 %393, i64 %394, i64 %395
  call void @llvm.lifetime.start.p0(i64 772, ptr nonnull %6) #6
  %397 = icmp sgt i64 %396, -1
  br i1 %397, label %430, label %432

398:                                              ; preds = %376, %427
  %399 = phi i32 [ %428, %427 ], [ 0, %376 ]
  %400 = load i32, ptr %379, align 4
  %401 = icmp eq i32 %400, 0
  br i1 %401, label %402, label %408

402:                                              ; preds = %408, %398
  %403 = phi i64 [ 0, %398 ], [ %417, %408 ]
  %404 = phi i32 [ %400, %398 ], [ %419, %408 ]
  %405 = icmp ne i64 %403, 0
  %406 = icmp ult i32 %404, 192
  %407 = and i1 %405, %406
  br i1 %407, label %422, label %427

408:                                              ; preds = %398, %408
  %409 = phi i64 [ %418, %408 ], [ 0, %398 ]
  %410 = phi i64 [ %417, %408 ], [ 0, %398 ]
  %411 = getelementptr inbounds nuw [192 x i32], ptr %4, i64 0, i64 %409
  %412 = load i32, ptr %411, align 4
  %413 = zext i32 %412 to i64
  %414 = mul nuw nsw i64 %413, 5
  %415 = add nuw nsw i64 %414, %410
  %416 = trunc i64 %415 to i32
  store i32 %416, ptr %411, align 4
  %417 = lshr i64 %415, 32
  %418 = add nuw nsw i64 %409, 1
  %419 = load i32, ptr %379, align 4
  %420 = zext i32 %419 to i64
  %421 = icmp samesign ult i64 %418, %420
  br i1 %421, label %408, label %402

422:                                              ; preds = %402
  %423 = trunc nuw nsw i64 %403 to i32
  %424 = add nuw nsw i32 %404, 1
  store i32 %424, ptr %379, align 4
  %425 = zext nneg i32 %404 to i64
  %426 = getelementptr inbounds nuw [192 x i32], ptr %4, i64 0, i64 %425
  store i32 %423, ptr %426, align 4
  br label %427

427:                                              ; preds = %402, %422
  %428 = add nuw i32 %399, 1
  %429 = icmp eq i32 %428, %378
  br i1 %429, label %381, label %398

430:                                              ; preds = %381
  %431 = trunc i64 %396 to i32
  call fastcc void @shl(ptr noundef %5, ptr noundef %3, i32 noundef %431)
  call void @llvm.memcpy.p0.p0.i64(ptr noundef nonnull align 4 dereferenceable(772) %6, ptr noundef nonnull align 4 dereferenceable(772) %4, i64 772, i1 false)
  br label %435

432:                                              ; preds = %381
  call void @llvm.memcpy.p0.p0.i64(ptr noundef nonnull align 4 dereferenceable(772) %5, ptr noundef nonnull align 4 dereferenceable(772) %3, i64 772, i1 false)
  %433 = trunc i64 %396 to i32
  %434 = sub i32 0, %433
  call fastcc void @shl(ptr noundef %6, ptr noundef %4, i32 noundef %434)
  br label %435

435:                                              ; preds = %432, %430
  %436 = call fastcc i64 @quotient(ptr noundef %5, ptr noundef %6)
  call void @llvm.lifetime.start.p0(i64 772, ptr nonnull %7) #6
  call fastcc void @shl(ptr noundef %7, ptr noundef %5, i32 noundef 1)
  %437 = getelementptr inbounds nuw i8, ptr %7, i64 768
  %438 = load i32, ptr %437, align 4
  %439 = getelementptr inbounds nuw i8, ptr %6, i64 768
  %440 = load i32, ptr %439, align 4
  %441 = icmp eq i32 %438, %440
  br i1 %441, label %442, label %444

442:                                              ; preds = %435
  %443 = zext i32 %438 to i64
  br label %447

444:                                              ; preds = %435
  %445 = icmp ugt i32 %438, %440
  %446 = select i1 %445, i32 1, i32 -1
  br label %460

447:                                              ; preds = %450, %442
  %448 = phi i64 [ %443, %442 ], [ %451, %450 ]
  %449 = icmp eq i64 %448, 0
  br i1 %449, label %460, label %450

450:                                              ; preds = %447
  %451 = add nsw i64 %448, -1
  %452 = getelementptr inbounds nuw [192 x i32], ptr %7, i64 0, i64 %451
  %453 = load i32, ptr %452, align 4
  %454 = getelementptr inbounds nuw [192 x i32], ptr %6, i64 0, i64 %451
  %455 = load i32, ptr %454, align 4
  %456 = icmp eq i32 %453, %455
  br i1 %456, label %447, label %457

457:                                              ; preds = %450
  %458 = icmp ugt i32 %453, %455
  %459 = select i1 %458, i32 1, i32 -1
  br label %460

460:                                              ; preds = %447, %444, %457
  %461 = phi i32 [ %446, %444 ], [ %459, %457 ], [ 0, %447 ]
  %462 = icmp sgt i32 %461, 0
  br i1 %462, label %469, label %463

463:                                              ; preds = %460
  %464 = icmp eq i32 %461, 0
  br i1 %464, label %465, label %471

465:                                              ; preds = %463
  %466 = and i64 %436, 1
  %467 = icmp eq i64 %466, 0
  %468 = select i1 %139, i1 %467, i1 false
  br i1 %468, label %471, label %469

469:                                              ; preds = %465, %460
  %470 = add i64 %436, 1
  br label %471

471:                                              ; preds = %465, %469, %463
  %472 = phi i64 [ %470, %469 ], [ %436, %463 ], [ %436, %465 ]
  br i1 %393, label %473, label %485

473:                                              ; preds = %471
  %474 = icmp eq i64 %472, 9007199254740992
  %475 = zext i1 %474 to i64
  %476 = add nsw i64 %392, %475
  %477 = icmp sgt i64 %476, 1023
  br i1 %477, label %495, label %478

478:                                              ; preds = %473
  %479 = shl i64 %476, 52
  %480 = add i64 %479, 4607182418800017408
  %481 = and i64 %472, 4503599627370495
  %482 = or disjoint i64 %480, %481
  %483 = or i64 %482, %15
  %484 = insertvalue { i32, i64 } { i32 0, i64 poison }, i64 %483, 1
  br label %495

485:                                              ; preds = %471
  %486 = icmp eq i64 %472, 0
  br i1 %486, label %495, label %487

487:                                              ; preds = %485
  %488 = icmp ugt i64 %472, 4503599627370495
  br i1 %488, label %489, label %492

489:                                              ; preds = %487
  %490 = or disjoint i64 %15, 4503599627370496
  %491 = insertvalue { i32, i64 } { i32 0, i64 poison }, i64 %490, 1
  br label %495

492:                                              ; preds = %487
  %493 = or disjoint i64 %472, %15
  %494 = insertvalue { i32, i64 } { i32 0, i64 poison }, i64 %493, 1
  br label %495

495:                                              ; preds = %485, %473, %492, %489, %478
  %496 = phi { i32, i64 } [ %484, %478 ], [ %491, %489 ], [ %494, %492 ], [ { i32 2, i64 0 }, %473 ], [ { i32 3, i64 0 }, %485 ]
  call void @llvm.lifetime.end.p0(i64 772, ptr nonnull %7) #6
  call void @llvm.lifetime.end.p0(i64 772, ptr nonnull %6) #6
  call void @llvm.lifetime.end.p0(i64 772, ptr nonnull %4) #6
  br label %497

497:                                              ; preds = %361, %246, %243, %369, %495, %199
  %498 = phi { i32, i64 } [ %200, %199 ], [ %496, %495 ], [ %375, %369 ], [ { i32 2, i64 0 }, %243 ], [ { i32 3, i64 0 }, %246 ], [ { i32 2, i64 0 }, %361 ]
  %499 = extractvalue { i32, i64 } %498, 1
  %500 = extractvalue { i32, i64 } %498, 0
  br label %501

501:                                              ; preds = %193, %189, %497
  %502 = phi i32 [ %500, %497 ], [ 1, %189 ], [ 1, %193 ]
  %503 = phi i64 [ %499, %497 ], [ 0, %189 ], [ 0, %193 ]
  %504 = insertvalue { i32, i64 } poison, i32 %502, 0
  %505 = insertvalue { i32, i64 } %504, i64 %503, 1
  br label %506

506:                                              ; preds = %136, %501
  %507 = phi { i32, i64 } [ %505, %501 ], [ { i32 1, i64 0 }, %136 ]
  call void @llvm.lifetime.end.p0(i64 772, ptr nonnull %3) #6
  ret { i32, i64 } %507
}

; Function Attrs: mustprogress nocallback nofree nosync nounwind willreturn memory(argmem: readwrite)
declare void @llvm.lifetime.start.p0(i64 immarg, ptr captures(none)) #1

; Function Attrs: mustprogress nocallback nofree nosync nounwind willreturn memory(argmem: readwrite)
declare void @llvm.lifetime.end.p0(i64 immarg, ptr captures(none)) #1

; Function Attrs: nofree norecurse nosync nounwind memory(argmem: read) uwtable
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
  %10 = getelementptr inbounds nuw [192 x i32], ptr %0, i64 0, i64 %9
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

; Function Attrs: nofree norecurse nosync nounwind memory(argmem: read) uwtable
define internal fastcc range(i32 -1, 2) i32 @low_half_cmp(ptr noundef nonnull readonly captures(none) %0, i32 noundef range(i32 1, 0) %1) unnamed_addr #0 {
  %3 = add i32 %1, -1
  %4 = lshr i32 %3, 5
  %5 = and i32 %3, 31
  %6 = getelementptr inbounds nuw i8, ptr %0, i64 768
  %7 = load i32, ptr %6, align 4
  %8 = icmp ult i32 %4, %7
  br i1 %8, label %9, label %35

9:                                                ; preds = %2
  %10 = zext nneg i32 %4 to i64
  %11 = getelementptr inbounds nuw [192 x i32], ptr %0, i64 0, i64 %10
  %12 = load i32, ptr %11, align 4
  %13 = shl nuw i32 1, %5
  %14 = and i32 %12, %13
  %15 = icmp eq i32 %14, 0
  br i1 %15, label %35, label %16

16:                                               ; preds = %9
  %17 = shl nsw i32 -1, %5
  %18 = xor i32 %17, -1
  %19 = and i32 %12, %18
  %20 = icmp eq i32 %19, 0
  br i1 %20, label %21, label %35

21:                                               ; preds = %16
  %22 = icmp ugt i32 %3, 31
  br i1 %22, label %23, label %35

23:                                               ; preds = %21
  %24 = tail call i32 @llvm.umin.i32(i32 %4, i32 %7)
  %25 = tail call i32 @llvm.umax.i32(i32 %24, i32 1)
  %26 = zext nneg i32 %25 to i64
  br label %30

27:                                               ; preds = %30
  %28 = add nuw nsw i64 %31, 1
  %29 = icmp eq i64 %28, %26
  br i1 %29, label %35, label %30

30:                                               ; preds = %23, %27
  %31 = phi i64 [ 0, %23 ], [ %28, %27 ]
  %32 = getelementptr inbounds nuw [192 x i32], ptr %0, i64 0, i64 %31
  %33 = load i32, ptr %32, align 4
  %34 = icmp eq i32 %33, 0
  br i1 %34, label %27, label %35

35:                                               ; preds = %30, %27, %21, %2, %9, %16
  %36 = phi i32 [ -1, %9 ], [ 1, %16 ], [ -1, %2 ], [ 0, %21 ], [ 0, %27 ], [ 1, %30 ]
  ret i32 %36
}

; Function Attrs: nofree norecurse nosync nounwind memory(argmem: read) uwtable
define internal fastcc range(i32 -1, 2) i32 @cmp_shift(ptr noundef nonnull readonly captures(none) %0, ptr noundef nonnull readonly captures(none) %1, i64 noundef range(i64 -4294967295, 4294967296) %2) unnamed_addr #0 {
  %4 = alloca %struct.Big, align 4
  call void @llvm.lifetime.start.p0(i64 772, ptr nonnull %4) #6
  %5 = icmp sgt i64 %2, -1
  %6 = trunc i64 %2 to i32
  br i1 %5, label %7, label %86

7:                                                ; preds = %3
  %8 = getelementptr inbounds nuw i8, ptr %4, i64 768
  %9 = lshr i32 %6, 5
  %10 = and i32 %6, 31
  %11 = getelementptr inbounds nuw i8, ptr %1, i64 768
  call void @llvm.memset.p0.i64(ptr noundef nonnull align 4 dereferenceable(772) %4, i8 0, i64 772, i1 false)
  %12 = load i32, ptr %11, align 4
  %13 = icmp ne i32 %10, 0
  %14 = zext i1 %13 to i32
  %15 = add i32 %12, %9
  %16 = add i32 %15, %14
  %17 = icmp ugt i32 %16, 192
  br i1 %17, label %63, label %18

18:                                               ; preds = %7
  %19 = icmp eq i32 %12, 0
  br i1 %19, label %23, label %20

20:                                               ; preds = %18
  %21 = and i64 %2, 31
  %22 = zext i32 %12 to i64
  br label %27

23:                                               ; preds = %27, %18
  %24 = phi i64 [ 0, %18 ], [ %40, %27 ]
  %25 = add i32 %12, %9
  store i32 %25, ptr %8, align 4
  %26 = icmp eq i64 %24, 0
  br i1 %26, label %48, label %43

27:                                               ; preds = %27, %20
  %28 = phi i64 [ 0, %20 ], [ %41, %27 ]
  %29 = phi i64 [ 0, %20 ], [ %40, %27 ]
  %30 = getelementptr inbounds nuw [192 x i32], ptr %1, i64 0, i64 %28
  %31 = load i32, ptr %30, align 4
  %32 = zext i32 %31 to i64
  %33 = shl nuw nsw i64 %32, %21
  %34 = or i64 %33, %29
  %35 = trunc i64 %34 to i32
  %36 = trunc nuw i64 %28 to i32
  %37 = add i32 %9, %36
  %38 = zext i32 %37 to i64
  %39 = getelementptr inbounds nuw [192 x i32], ptr %4, i64 0, i64 %38
  store i32 %35, ptr %39, align 4
  %40 = lshr i64 %33, 32
  %41 = add nuw nsw i64 %28, 1
  %42 = icmp eq i64 %41, %22
  br i1 %42, label %23, label %27

43:                                               ; preds = %23
  %44 = trunc nuw nsw i64 %24 to i32
  %45 = add i32 %25, 1
  store i32 %45, ptr %8, align 4
  %46 = zext i32 %25 to i64
  %47 = getelementptr inbounds nuw [192 x i32], ptr %4, i64 0, i64 %46
  store i32 %44, ptr %47, align 4
  br label %48

48:                                               ; preds = %43, %23
  %49 = load i32, ptr %8, align 4
  %50 = icmp eq i32 %49, 0
  br i1 %50, label %63, label %51

51:                                               ; preds = %48
  %52 = zext i32 %49 to i64
  br label %53

53:                                               ; preds = %60, %51
  %54 = phi i64 [ %52, %51 ], [ %55, %60 ]
  %55 = add nsw i64 %54, -1
  %56 = and i64 %55, 4294967295
  %57 = getelementptr inbounds nuw [192 x i32], ptr %4, i64 0, i64 %56
  %58 = load i32, ptr %57, align 4
  %59 = icmp eq i32 %58, 0
  br i1 %59, label %60, label %63

60:                                               ; preds = %53
  %61 = trunc i64 %55 to i32
  store i32 %61, ptr %8, align 4
  %62 = icmp eq i32 %61, 0
  br i1 %62, label %63, label %53

63:                                               ; preds = %53, %60, %7, %48
  %64 = getelementptr inbounds nuw i8, ptr %0, i64 768
  %65 = load i32, ptr %64, align 4
  %66 = load i32, ptr %8, align 4
  %67 = icmp eq i32 %65, %66
  br i1 %67, label %68, label %70

68:                                               ; preds = %63
  %69 = zext i32 %65 to i64
  br label %73

70:                                               ; preds = %63
  %71 = icmp ugt i32 %65, %66
  %72 = select i1 %71, i32 1, i32 -1
  br label %166

73:                                               ; preds = %76, %68
  %74 = phi i64 [ %69, %68 ], [ %77, %76 ]
  %75 = icmp eq i64 %74, 0
  br i1 %75, label %166, label %76

76:                                               ; preds = %73
  %77 = add nsw i64 %74, -1
  %78 = getelementptr inbounds nuw [192 x i32], ptr %0, i64 0, i64 %77
  %79 = load i32, ptr %78, align 4
  %80 = getelementptr inbounds nuw [192 x i32], ptr %4, i64 0, i64 %77
  %81 = load i32, ptr %80, align 4
  %82 = icmp eq i32 %79, %81
  br i1 %82, label %73, label %83

83:                                               ; preds = %76
  %84 = icmp ugt i32 %79, %81
  %85 = select i1 %84, i32 1, i32 -1
  br label %166

86:                                               ; preds = %3
  %87 = sub i32 0, %6
  %88 = getelementptr inbounds nuw i8, ptr %4, i64 768
  %89 = lshr i32 %87, 5
  %90 = and i32 %87, 31
  %91 = getelementptr inbounds nuw i8, ptr %0, i64 768
  call void @llvm.memset.p0.i64(ptr noundef nonnull align 4 dereferenceable(772) %4, i8 0, i64 772, i1 false)
  %92 = load i32, ptr %91, align 4
  %93 = icmp ne i32 %90, 0
  %94 = zext i1 %93 to i32
  %95 = add i32 %92, %89
  %96 = add i32 %95, %94
  %97 = icmp ugt i32 %96, 192
  br i1 %97, label %143, label %98

98:                                               ; preds = %86
  %99 = icmp eq i32 %92, 0
  br i1 %99, label %103, label %100

100:                                              ; preds = %98
  %101 = zext nneg i32 %90 to i64
  %102 = zext i32 %92 to i64
  br label %107

103:                                              ; preds = %107, %98
  %104 = phi i64 [ 0, %98 ], [ %120, %107 ]
  %105 = add i32 %92, %89
  store i32 %105, ptr %88, align 4
  %106 = icmp eq i64 %104, 0
  br i1 %106, label %128, label %123

107:                                              ; preds = %107, %100
  %108 = phi i64 [ 0, %100 ], [ %121, %107 ]
  %109 = phi i64 [ 0, %100 ], [ %120, %107 ]
  %110 = getelementptr inbounds nuw [192 x i32], ptr %0, i64 0, i64 %108
  %111 = load i32, ptr %110, align 4
  %112 = zext i32 %111 to i64
  %113 = shl nuw nsw i64 %112, %101
  %114 = or i64 %113, %109
  %115 = trunc i64 %114 to i32
  %116 = trunc nuw i64 %108 to i32
  %117 = add i32 %89, %116
  %118 = zext i32 %117 to i64
  %119 = getelementptr inbounds nuw [192 x i32], ptr %4, i64 0, i64 %118
  store i32 %115, ptr %119, align 4
  %120 = lshr i64 %113, 32
  %121 = add nuw nsw i64 %108, 1
  %122 = icmp eq i64 %121, %102
  br i1 %122, label %103, label %107

123:                                              ; preds = %103
  %124 = trunc nuw nsw i64 %104 to i32
  %125 = add i32 %105, 1
  store i32 %125, ptr %88, align 4
  %126 = zext i32 %105 to i64
  %127 = getelementptr inbounds nuw [192 x i32], ptr %4, i64 0, i64 %126
  store i32 %124, ptr %127, align 4
  br label %128

128:                                              ; preds = %123, %103
  %129 = load i32, ptr %88, align 4
  %130 = icmp eq i32 %129, 0
  br i1 %130, label %143, label %131

131:                                              ; preds = %128
  %132 = zext i32 %129 to i64
  br label %133

133:                                              ; preds = %140, %131
  %134 = phi i64 [ %132, %131 ], [ %135, %140 ]
  %135 = add nsw i64 %134, -1
  %136 = and i64 %135, 4294967295
  %137 = getelementptr inbounds nuw [192 x i32], ptr %4, i64 0, i64 %136
  %138 = load i32, ptr %137, align 4
  %139 = icmp eq i32 %138, 0
  br i1 %139, label %140, label %143

140:                                              ; preds = %133
  %141 = trunc i64 %135 to i32
  store i32 %141, ptr %88, align 4
  %142 = icmp eq i32 %141, 0
  br i1 %142, label %143, label %133

143:                                              ; preds = %133, %140, %86, %128
  %144 = load i32, ptr %88, align 4
  %145 = getelementptr inbounds nuw i8, ptr %1, i64 768
  %146 = load i32, ptr %145, align 4
  %147 = icmp eq i32 %144, %146
  br i1 %147, label %148, label %150

148:                                              ; preds = %143
  %149 = zext i32 %144 to i64
  br label %153

150:                                              ; preds = %143
  %151 = icmp ugt i32 %144, %146
  %152 = select i1 %151, i32 1, i32 -1
  br label %166

153:                                              ; preds = %156, %148
  %154 = phi i64 [ %149, %148 ], [ %157, %156 ]
  %155 = icmp eq i64 %154, 0
  br i1 %155, label %166, label %156

156:                                              ; preds = %153
  %157 = add nsw i64 %154, -1
  %158 = getelementptr inbounds nuw [192 x i32], ptr %4, i64 0, i64 %157
  %159 = load i32, ptr %158, align 4
  %160 = getelementptr inbounds nuw [192 x i32], ptr %1, i64 0, i64 %157
  %161 = load i32, ptr %160, align 4
  %162 = icmp eq i32 %159, %161
  br i1 %162, label %153, label %163

163:                                              ; preds = %156
  %164 = icmp ugt i32 %159, %161
  %165 = select i1 %164, i32 1, i32 -1
  br label %166

166:                                              ; preds = %153, %73, %163, %150, %83, %70
  %167 = phi i32 [ %72, %70 ], [ %85, %83 ], [ %152, %150 ], [ %165, %163 ], [ 0, %73 ], [ 0, %153 ]
  call void @llvm.lifetime.end.p0(i64 772, ptr nonnull %4) #6
  ret i32 %167
}

; Function Attrs: nofree norecurse nosync nounwind memory(argmem: readwrite) uwtable
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
  %21 = phi i32 [ %15, %14 ], [ %39, %24 ]
  %22 = add i32 %21, %5
  store i32 %22, ptr %4, align 4
  %23 = icmp eq i64 %20, 0
  br i1 %23, label %47, label %42

24:                                               ; preds = %17, %24
  %25 = phi i64 [ 0, %17 ], [ %38, %24 ]
  %26 = phi i64 [ 0, %17 ], [ %37, %24 ]
  %27 = getelementptr inbounds nuw [192 x i32], ptr %1, i64 0, i64 %25
  %28 = load i32, ptr %27, align 4
  %29 = zext i32 %28 to i64
  %30 = shl nuw nsw i64 %29, %18
  %31 = or i64 %30, %26
  %32 = trunc i64 %31 to i32
  %33 = trunc nuw i64 %25 to i32
  %34 = add i32 %5, %33
  %35 = zext i32 %34 to i64
  %36 = getelementptr inbounds nuw [192 x i32], ptr %0, i64 0, i64 %35
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
  %46 = getelementptr inbounds nuw [192 x i32], ptr %0, i64 0, i64 %45
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
  %56 = getelementptr inbounds nuw [192 x i32], ptr %0, i64 0, i64 %55
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

; Function Attrs: nofree norecurse nosync nounwind memory(argmem: readwrite) uwtable
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
  %12 = getelementptr inbounds nuw [192 x i32], ptr %0, i64 0, i64 %11
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
  %38 = getelementptr inbounds nuw [192 x i32], ptr %1, i64 0, i64 %37
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

61:                                               ; preds = %188, %54
  %62 = phi i64 [ 0, %54 ], [ %189, %188 ]
  ret i64 %62

63:                                               ; preds = %58, %188
  %64 = phi i64 [ %60, %58 ], [ %190, %188 ]
  %65 = phi i64 [ 0, %58 ], [ %189, %188 ]
  call void @llvm.lifetime.start.p0(i64 772, ptr nonnull %3) #6
  %66 = trunc nuw nsw i64 %64 to i32
  %67 = lshr i32 %66, 5
  call void @llvm.memset.p0.i64(ptr noundef nonnull align 4 dereferenceable(772) %3, i8 0, i64 772, i1 false)
  %68 = load i32, ptr %30, align 4
  %69 = and i64 %64, 31
  %70 = icmp ne i64 %69, 0
  %71 = zext i1 %70 to i32
  %72 = add i32 %68, %67
  %73 = add i32 %72, %71
  %74 = icmp ugt i32 %73, 192
  br i1 %74, label %120, label %75

75:                                               ; preds = %63
  %76 = icmp eq i32 %68, 0
  br i1 %76, label %80, label %77

77:                                               ; preds = %75
  %78 = and i64 %64, 31
  %79 = zext i32 %68 to i64
  br label %84

80:                                               ; preds = %84, %75
  %81 = phi i64 [ 0, %75 ], [ %97, %84 ]
  %82 = add i32 %68, %67
  store i32 %82, ptr %59, align 4
  %83 = icmp eq i64 %81, 0
  br i1 %83, label %105, label %100

84:                                               ; preds = %84, %77
  %85 = phi i64 [ 0, %77 ], [ %98, %84 ]
  %86 = phi i64 [ 0, %77 ], [ %97, %84 ]
  %87 = getelementptr inbounds nuw [192 x i32], ptr %1, i64 0, i64 %85
  %88 = load i32, ptr %87, align 4
  %89 = zext i32 %88 to i64
  %90 = shl nuw nsw i64 %89, %78
  %91 = or i64 %90, %86
  %92 = trunc i64 %91 to i32
  %93 = trunc nuw i64 %85 to i32
  %94 = add i32 %67, %93
  %95 = zext i32 %94 to i64
  %96 = getelementptr inbounds nuw [192 x i32], ptr %3, i64 0, i64 %95
  store i32 %92, ptr %96, align 4
  %97 = lshr i64 %90, 32
  %98 = add nuw nsw i64 %85, 1
  %99 = icmp eq i64 %98, %79
  br i1 %99, label %80, label %84

100:                                              ; preds = %80
  %101 = trunc nuw nsw i64 %81 to i32
  %102 = add i32 %82, 1
  store i32 %102, ptr %59, align 4
  %103 = zext i32 %82 to i64
  %104 = getelementptr inbounds nuw [192 x i32], ptr %3, i64 0, i64 %103
  store i32 %101, ptr %104, align 4
  br label %105

105:                                              ; preds = %100, %80
  %106 = load i32, ptr %59, align 4
  %107 = icmp eq i32 %106, 0
  br i1 %107, label %120, label %108

108:                                              ; preds = %105
  %109 = zext i32 %106 to i64
  br label %110

110:                                              ; preds = %117, %108
  %111 = phi i64 [ %109, %108 ], [ %112, %117 ]
  %112 = add nsw i64 %111, -1
  %113 = and i64 %112, 4294967295
  %114 = getelementptr inbounds nuw [192 x i32], ptr %3, i64 0, i64 %113
  %115 = load i32, ptr %114, align 4
  %116 = icmp eq i32 %115, 0
  br i1 %116, label %117, label %120

117:                                              ; preds = %110
  %118 = trunc i64 %112 to i32
  store i32 %118, ptr %59, align 4
  %119 = icmp eq i32 %118, 0
  br i1 %119, label %120, label %110

120:                                              ; preds = %110, %117, %63, %105
  %121 = load i32, ptr %4, align 4
  %122 = load i32, ptr %59, align 4
  %123 = icmp eq i32 %121, %122
  br i1 %123, label %124, label %126

124:                                              ; preds = %120
  %125 = zext i32 %121 to i64
  br label %128

126:                                              ; preds = %120
  %127 = icmp ugt i32 %121, %122
  br label %140

128:                                              ; preds = %131, %124
  %129 = phi i64 [ %125, %124 ], [ %132, %131 ]
  %130 = icmp eq i64 %129, 0
  br i1 %130, label %142, label %131

131:                                              ; preds = %128
  %132 = add nsw i64 %129, -1
  %133 = getelementptr inbounds nuw [192 x i32], ptr %0, i64 0, i64 %132
  %134 = load i32, ptr %133, align 4
  %135 = getelementptr inbounds nuw [192 x i32], ptr %3, i64 0, i64 %132
  %136 = load i32, ptr %135, align 4
  %137 = icmp eq i32 %134, %136
  br i1 %137, label %128, label %138

138:                                              ; preds = %131
  %139 = icmp ugt i32 %134, %136
  br label %140

140:                                              ; preds = %126, %138
  %141 = phi i1 [ %127, %126 ], [ %139, %138 ]
  br i1 %141, label %142, label %188

142:                                              ; preds = %128, %140
  %143 = icmp eq i32 %121, 0
  br i1 %143, label %146, label %144

144:                                              ; preds = %142
  %145 = zext i32 %122 to i64
  br label %161

146:                                              ; preds = %172, %142
  %147 = phi i32 [ %121, %142 ], [ %180, %172 ]
  %148 = icmp eq i32 %147, 0
  br i1 %148, label %183, label %149

149:                                              ; preds = %146
  %150 = zext i32 %147 to i64
  br label %151

151:                                              ; preds = %158, %149
  %152 = phi i64 [ %150, %149 ], [ %153, %158 ]
  %153 = add nsw i64 %152, -1
  %154 = and i64 %153, 4294967295
  %155 = getelementptr inbounds nuw [192 x i32], ptr %0, i64 0, i64 %154
  %156 = load i32, ptr %155, align 4
  %157 = icmp eq i32 %156, 0
  br i1 %157, label %158, label %183

158:                                              ; preds = %151
  %159 = trunc i64 %153 to i32
  store i32 %159, ptr %4, align 4
  %160 = icmp eq i32 %159, 0
  br i1 %160, label %183, label %151

161:                                              ; preds = %144, %172
  %162 = phi i64 [ %179, %172 ], [ 0, %144 ]
  %163 = phi i64 [ %178, %172 ], [ 0, %144 ]
  %164 = getelementptr inbounds nuw [192 x i32], ptr %0, i64 0, i64 %162
  %165 = load i32, ptr %164, align 4
  %166 = zext i32 %165 to i64
  %167 = icmp samesign ult i64 %162, %145
  br i1 %167, label %168, label %172

168:                                              ; preds = %161
  %169 = getelementptr inbounds nuw [192 x i32], ptr %3, i64 0, i64 %162
  %170 = load i32, ptr %169, align 4
  %171 = zext i32 %170 to i64
  br label %172

172:                                              ; preds = %168, %161
  %173 = phi i64 [ %171, %168 ], [ 0, %161 ]
  %174 = add nuw nsw i64 %173, %163
  %175 = trunc i64 %174 to i32
  %176 = sub i32 %165, %175
  store i32 %176, ptr %164, align 4
  %177 = icmp samesign ugt i64 %174, %166
  %178 = zext i1 %177 to i64
  %179 = add nuw nsw i64 %162, 1
  %180 = load i32, ptr %4, align 4
  %181 = zext i32 %180 to i64
  %182 = icmp samesign ult i64 %179, %181
  br i1 %182, label %161, label %146

183:                                              ; preds = %151, %158, %146
  %184 = icmp slt i64 %64, 64
  br i1 %184, label %185, label %188

185:                                              ; preds = %183
  %186 = shl nuw i64 1, %64
  %187 = or i64 %186, %65
  br label %188

188:                                              ; preds = %183, %185, %140
  %189 = phi i64 [ %187, %185 ], [ %65, %183 ], [ %65, %140 ]
  call void @llvm.lifetime.end.p0(i64 772, ptr nonnull %3) #6
  %190 = add nsw i64 %64, -1
  %191 = icmp sgt i64 %64, 0
  br i1 %191, label %63, label %61
}

; Function Attrs: nocallback nofree nosync nounwind speculatable willreturn memory(none)
declare i32 @llvm.usub.sat.i32(i32, i32) #4

; Function Attrs: nocallback nofree nosync nounwind speculatable willreturn memory(none)
declare i64 @llvm.smin.i64(i64, i64) #4

; Function Attrs: nocallback nofree nounwind willreturn memory(argmem: write)
declare void @llvm.memset.p0.i64(ptr writeonly captures(none), i8, i64, i1 immarg) #5

; Function Attrs: nocallback nofree nosync nounwind speculatable willreturn memory(none)
declare i32 @llvm.umin.i32(i32, i32) #4

; Function Attrs: nocallback nofree nosync nounwind speculatable willreturn memory(none)
declare i32 @llvm.umax.i32(i32, i32) #4

attributes #0 = { nofree norecurse nosync nounwind memory(argmem: read) uwtable "min-legal-vector-width"="0" "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-cpu"="x86-64" "target-features"="+cmov,+cx8,+fxsr,+mmx,+sse,+sse2,+x87" "tune-cpu"="generic" }
attributes #1 = { mustprogress nocallback nofree nosync nounwind willreturn memory(argmem: readwrite) }
attributes #2 = { nofree norecurse nosync nounwind memory(argmem: readwrite) uwtable "min-legal-vector-width"="0" "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-cpu"="x86-64" "target-features"="+cmov,+cx8,+fxsr,+mmx,+sse,+sse2,+x87" "tune-cpu"="generic" }
attributes #3 = { mustprogress nocallback nofree nounwind willreturn memory(argmem: readwrite) }
attributes #4 = { nocallback nofree nosync nounwind speculatable willreturn memory(none) }
attributes #5 = { nocallback nofree nounwind willreturn memory(argmem: write) }
attributes #6 = { nounwind }
