/*
 * Aether NUMERIC-PARSING-V1 private runtime.
 *
 * This source is the auditable authority for numeric_parse_runtime.inc.  It is
 * compiled with clang -O1 -S -emit-llvm -fno-math-errno and stripped of module
 * headers, duplicate memcpy declarations and metadata before embedding.  The implementation
 * uses only integer arithmetic, so decimal conversion is independent of the
 * host locale and floating-point rounding mode.
 */
typedef unsigned char u8;
typedef unsigned int u32;
typedef unsigned long long u64;
typedef long long i64;

typedef struct { u32 limb[192]; u32 n; } Big;
typedef struct { u32 status; u64 bits; } ParseDouble;

static void zero(Big *a) { for (u32 i=0;i<192;i++) a->limb[i]=0; a->n=0; }
static void norm(Big *a) { while (a->n && !a->limb[a->n-1]) a->n--; }
static void mul_small(Big *a,u32 m) {
  u64 carry=0;
  for(u32 i=0;i<a->n;i++){u64 x=(u64)a->limb[i]*m+carry;a->limb[i]=(u32)x;carry=x>>32;}
  if(carry && a->n<192)a->limb[a->n++]=(u32)carry;
}
static void add_small(Big *a,u32 v){
  u64 carry=v;u32 i=0;
  while(carry && i<a->n){u64 x=(u64)a->limb[i]+carry;a->limb[i]=(u32)x;carry=x>>32;i++;}
  if(carry && a->n<192)a->limb[a->n++]=(u32)carry;
}
static u32 clz32(u32 x){u32 n=0;if(!x)return 32;while(!(x&0x80000000u)){x<<=1;n++;}return n;}
static u32 bits(const Big *a){return a->n?32*(a->n-1)+32-clz32(a->limb[a->n-1]):0;}
static int cmp(const Big *a,const Big *b){
  if(a->n!=b->n)return a->n>b->n?1:-1;
  for(u32 i=a->n;i;i--){if(a->limb[i-1]!=b->limb[i-1])return a->limb[i-1]>b->limb[i-1]?1:-1;}
  return 0;
}
static void sub(Big *a,const Big *b){
  u64 borrow=0;
  for(u32 i=0;i<a->n;i++){u64 av=a->limb[i],bv=i<b->n?b->limb[i]:0;u64 x=av-bv-borrow;a->limb[i]=(u32)x;borrow=av<bv+borrow;}
  norm(a);
}
static void shl(Big *out,const Big *in,u32 shift){
  zero(out);u32 words=shift/32,part=shift%32;if(in->n+words+(part!=0)>192)return;
  u64 carry=0;for(u32 i=0;i<in->n;i++){u64 x=((u64)in->limb[i]<<part)|carry;out->limb[i+words]=(u32)x;carry=x>>32;}
  out->n=in->n+words;if(carry)out->limb[out->n++]=(u32)carry;norm(out);
}
static u64 low64(const Big *a){u64 x=a->n?a->limb[0]:0;if(a->n>1)x|=(u64)a->limb[1]<<32;return x;}
static u32 bit_at(const Big *a,u32 bit){u32 w=bit/32;return w<a->n?((a->limb[w]>>(bit%32))&1):0;}
static u64 shr_low64(const Big *a,u32 shift){
  u64 x=0;for(u32 i=0;i<53;i++)if(bit_at(a,shift+i))x|=1ull<<i;return x;
}
static int low_half_cmp(const Big *a,u32 shift){
  if(!shift)return -1;u32 bit=shift-1,w=bit/32,p=bit%32;
  int half=(w<a->n)&&((a->limb[w]>>p)&1);
  if(!half)return -1;
  u32 mask=p?((1u<<p)-1):0;if(w<a->n && (a->limb[w]&mask))return 1;
  for(u32 i=0;i<w && i<a->n;i++)if(a->limb[i])return 1;
  return 0;
}
static int cmp_shift(const Big *a,const Big *b,i64 shift){
  Big t;if(shift>=0){shl(&t,b,(u32)shift);return cmp(a,&t);}shl(&t,a,(u32)-shift);return cmp(&t,b);
}
static u64 quotient(Big *rem,const Big *den){
  u64 q=0;int d=(int)bits(rem)-(int)bits(den);
  for(int i=d;i>=0;i--){Big t;shl(&t,den,(u32)i);if(cmp(rem,&t)>=0){sub(rem,&t);if(i<64)q|=1ull<<i;}}
  return q;
}
static i64 sat_add(i64 a,i64 b){if(b>0&&a>1000000-b)return 1000000;if(b<0&&a<-1000000-b)return -1000000;return a+b;}
static ParseDouble result(u32 status,u64 bits_value){ParseDouble r={status,bits_value};return r;}

/* status: 0 Value, 1 Invalid, 2 Overflow, 3 Underflow */
ParseDouble aether_numeric_parse_double(const u8 *s,u64 len){
  u64 i=0;u32 negative=0;if(i<len&&(s[i]=='+'||s[i]=='-')){negative=s[i]=='-';i++;}
  u32 saw_digit=0,saw_nonzero=0,dot=0;u64 frac=0,kept=0,omitted=0;u32 sticky=0;Big c;zero(&c);
  for(;i<len;i++){
    u8 ch=s[i];
    if(ch>='0'&&ch<='9'){
      saw_digit=1;if(dot&&frac<1000000)frac++;
      u32 d=ch-'0';if(!saw_nonzero){if(!d)continue;saw_nonzero=1;}
      if(kept<780){mul_small(&c,10);add_small(&c,d);kept++;}else{omitted++;if(d)sticky=1;}
    }else if(ch=='.'&&!dot){dot=1;}else break;
  }
  if(!saw_digit)return result(1,0);
  i64 exponent=0;u32 exp_negative=0;
  if(i<len&&(s[i]=='e'||s[i]=='E')){
    i++;if(i<len&&(s[i]=='+'||s[i]=='-')){exp_negative=s[i]=='-';i++;}
    u32 exp_digits=0;for(;i<len&&s[i]>='0'&&s[i]<='9';i++){exp_digits=1;if(exponent<1000000){exponent=exponent*10+(s[i]-'0');if(exponent>1000000)exponent=1000000;}}
    if(!exp_digits)return result(1,0);
  }
  if(i!=len)return result(1,0);
  u64 sign=(u64)negative<<63;if(!saw_nonzero)return result(0,sign);
  if(exp_negative)exponent=-exponent;
  i64 q=sat_add(exponent,-(i64)frac);q=sat_add(q,(i64)omitted);
  i64 scientific=sat_add((i64)kept,q-1);
  if(scientific>309)return result(2,0);if(scientific<-324)return result(3,0);
  u64 mant; i64 e;
  if(q>=0){
    for(i64 z=0;z<q;z++)mul_small(&c,5);
    u32 bl=bits(&c),cut=bl>53?bl-53:0;mant=cut?shr_low64(&c,cut):(low64(&c)<<(53-bl));
    if(cut){int hc=low_half_cmp(&c,cut);if(hc>0||(hc==0&&(sticky||(mant&1))))mant++;}
    e=(i64)bl-1+q;if(mant==(1ull<<53)){mant>>=1;e++;}
    if(e>1023)return result(2,0);
    u64 payload=((u64)(e+1023)<<52)|(mant&((1ull<<52)-1));return result(0,sign|payload);
  }
  u32 k=(u32)-q;Big den;zero(&den);den.n=1;den.limb[0]=1;for(u32 z=0;z<k;z++)mul_small(&den,5);
  i64 r=(i64)bits(&c)-(i64)bits(&den);if(cmp_shift(&c,&den,r)<0)r--;e=r-(i64)k;
  i64 scale=e>=-1022?52-r:1074-(i64)k;Big num,div;
  if(scale>=0){shl(&num,&c,(u32)scale);div=den;}else{num=c;shl(&div,&den,(u32)-scale);}
  Big rem=num;mant=quotient(&rem,&div);Big twice;shl(&twice,&rem,1);int hc=cmp(&twice,&div);
  if(hc>0||(hc==0&&(sticky||(mant&1))))mant++;
  if(e>=-1022){if(mant==(1ull<<53)){mant>>=1;e++;}if(e>1023)return result(2,0);return result(0,sign|((u64)(e+1023)<<52)|(mant&((1ull<<52)-1)));}
  if(!mant)return result(3,0);if(mant>=(1ull<<52))return result(0,sign|(1ull<<52));return result(0,sign|mant);
}
