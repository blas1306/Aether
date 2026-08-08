#include <stdio.h>
#include <math.h>

typedef struct {
    double raiz;
    double res;
    int iter;
} NewtonResultado;

double f(double x) {
    return x * exp(x) - 1;
}

double df(double x) {
    return exp(x) + x * exp(x);
}

NewtonResultado NR2(
    double (*f)(double),
    double (*df)(double),
    double x0,
    double tol,
    int maxiter
) {
    double x = x0;
    double res = fabs(f(x));
    int iter = 0;

    while (res > tol && iter < maxiter) {
        x = x - f(x) / df(x);
        res = fabs(f(x));
        iter++;
    }

    NewtonResultado result = {x, res, iter};
    return result;
}

int main(void) {
    double acc = 0;

    for (int i = 0; i <= 1000000; i++) {
        NewtonResultado nr = NR2(f, df, -0.99, 1e-8, 100);
        acc += nr.raiz;
    }

    printf("%.15g\n", acc);

    return 0;
}
