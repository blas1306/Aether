//! Shared strict UTF-8 validator for runtime byte-to-text boundaries.

#[allow(clippy::too_many_lines)]
pub(super) fn runtime(output: &mut String) {
    output.push_str(
        r"
define internal i1 @aether_utf8_validate(ptr %data, i64 %length) nounwind {
entry:
  br label %loop
loop:
  %i = phi i64 [ 0, %entry ], [ %next1, %ascii_advance ], [ %next2, %valid2 ], [ %next3, %valid3 ], [ %next4, %valid4 ]
  %done = icmp eq i64 %i, %length
  br i1 %done, label %valid, label %lead
lead:
  %p0 = getelementptr i8, ptr %data, i64 %i
  %b0raw = load i8, ptr %p0
  %b0 = zext i8 %b0raw to i32
  %ascii = icmp ult i32 %b0, 128
  br i1 %ascii, label %ascii_advance, label %test2
ascii_advance:
  %next1 = add i64 %i, 1
  br label %loop
test2:
  %lo2 = icmp uge i32 %b0, 194
  %hi2 = icmp ule i32 %b0, 223
  %is2 = and i1 %lo2, %hi2
  br i1 %is2, label %need2, label %test3
need2:
  %i1_2 = add i64 %i, 1
  %has2 = icmp ult i64 %i1_2, %length
  br i1 %has2, label %check2, label %invalid
check2:
  %p1_2 = getelementptr i8, ptr %data, i64 %i1_2
  %b1_2raw = load i8, ptr %p1_2
  %b1_2 = zext i8 %b1_2raw to i32
  %b1_2lo = icmp uge i32 %b1_2, 128
  %b1_2hi = icmp ule i32 %b1_2, 191
  %ok2 = and i1 %b1_2lo, %b1_2hi
  br i1 %ok2, label %valid2, label %invalid
valid2:
  %next2 = add i64 %i, 2
  br label %loop
test3:
  %lo3 = icmp uge i32 %b0, 224
  %hi3 = icmp ule i32 %b0, 239
  %is3 = and i1 %lo3, %hi3
  br i1 %is3, label %need3, label %test4
need3:
  %i2_3 = add i64 %i, 2
  %has3 = icmp ult i64 %i2_3, %length
  br i1 %has3, label %check3, label %invalid
check3:
  %i1_3 = add i64 %i, 1
  %p1_3 = getelementptr i8, ptr %data, i64 %i1_3
  %p2_3 = getelementptr i8, ptr %data, i64 %i2_3
  %b1_3raw = load i8, ptr %p1_3
  %b2_3raw = load i8, ptr %p2_3
  %b1_3 = zext i8 %b1_3raw to i32
  %b2_3 = zext i8 %b2_3raw to i32
  %b1_3lo = icmp uge i32 %b1_3, 128
  %b1_3hi = icmp ule i32 %b1_3, 191
  %b1_3normal = and i1 %b1_3lo, %b1_3hi
  %b2_3lo = icmp uge i32 %b2_3, 128
  %b2_3hi = icmp ule i32 %b2_3, 191
  %b2_3ok = and i1 %b2_3lo, %b2_3hi
  %e0 = icmp eq i32 %b0, 224
  %ed = icmp eq i32 %b0, 237
  %e0range = icmp uge i32 %b1_3, 160
  %edrange = icmp ule i32 %b1_3, 159
  %not_e0 = xor i1 %e0, true
  %not_ed = xor i1 %ed, true
  %e0ok = or i1 %not_e0, %e0range
  %edok = or i1 %not_ed, %edrange
  %b1_3a = and i1 %b1_3normal, %e0ok
  %b1_3ok = and i1 %b1_3a, %edok
  %ok3 = and i1 %b1_3ok, %b2_3ok
  br i1 %ok3, label %valid3, label %invalid
valid3:
  %next3 = add i64 %i, 3
  br label %loop
test4:
  %lo4 = icmp uge i32 %b0, 240
  %hi4 = icmp ule i32 %b0, 244
  %is4 = and i1 %lo4, %hi4
  br i1 %is4, label %need4, label %invalid
need4:
  %i3_4 = add i64 %i, 3
  %has4 = icmp ult i64 %i3_4, %length
  br i1 %has4, label %check4, label %invalid
check4:
  %i1_4 = add i64 %i, 1
  %i2_4 = add i64 %i, 2
  %p1_4 = getelementptr i8, ptr %data, i64 %i1_4
  %p2_4 = getelementptr i8, ptr %data, i64 %i2_4
  %p3_4 = getelementptr i8, ptr %data, i64 %i3_4
  %b1_4raw = load i8, ptr %p1_4
  %b2_4raw = load i8, ptr %p2_4
  %b3_4raw = load i8, ptr %p3_4
  %b1_4 = zext i8 %b1_4raw to i32
  %b2_4 = zext i8 %b2_4raw to i32
  %b3_4 = zext i8 %b3_4raw to i32
  %b1_4lo = icmp uge i32 %b1_4, 128
  %b1_4hi = icmp ule i32 %b1_4, 191
  %b1_4normal = and i1 %b1_4lo, %b1_4hi
  %b2_4lo = icmp uge i32 %b2_4, 128
  %b2_4hi = icmp ule i32 %b2_4, 191
  %b2_4ok = and i1 %b2_4lo, %b2_4hi
  %b3_4lo = icmp uge i32 %b3_4, 128
  %b3_4hi = icmp ule i32 %b3_4, 191
  %b3_4ok = and i1 %b3_4lo, %b3_4hi
  %f0 = icmp eq i32 %b0, 240
  %f4 = icmp eq i32 %b0, 244
  %f0range = icmp uge i32 %b1_4, 144
  %f4range = icmp ule i32 %b1_4, 143
  %not_f0 = xor i1 %f0, true
  %not_f4 = xor i1 %f4, true
  %f0ok = or i1 %not_f0, %f0range
  %f4ok = or i1 %not_f4, %f4range
  %b1_4a = and i1 %b1_4normal, %f0ok
  %b1_4ok = and i1 %b1_4a, %f4ok
  %ok4a = and i1 %b1_4ok, %b2_4ok
  %ok4 = and i1 %ok4a, %b3_4ok
  br i1 %ok4, label %valid4, label %invalid
valid4:
  %next4 = add i64 %i, 4
  br label %loop
valid:
  ret i1 true
invalid:
  ret i1 false
}
",
    );
}
