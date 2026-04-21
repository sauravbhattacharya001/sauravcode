#!/usr/bin/env python3
"""sauravmatrix — Interactive Matrix Calculator & Linear Algebra Toolkit.

A full-featured matrix calculator with REPL interface for the sauravcode
ecosystem. Supports creation, arithmetic, transformations, decompositions,
and solving linear systems — all with no external dependencies.

Usage:
    python sauravmatrix.py                  # Launch interactive REPL
    python sauravmatrix.py --demo           # Run built-in demos
    python sauravmatrix.py --eval "det(A)"  # One-shot evaluation
"""

import ast
import sys
import math
import copy
import re


# ── Matrix Class ────────────────────────────────────────────────────────────

class Matrix:
    """Dense matrix with pure-Python linear algebra operations."""

    __slots__ = ('rows', 'nrows', 'ncols')

    def __init__(self, data):
        if not data or not data[0]:
            raise ValueError("Matrix cannot be empty")
        self.rows = [list(row) for row in data]
        self.nrows = len(self.rows)
        self.ncols = len(self.rows[0])
        for r in self.rows:
            if len(r) != self.ncols:
                raise ValueError("All rows must have the same length")

    # ── Constructors ────────────────────────────────────────────────────

    @staticmethod
    def identity(n):
        """Return n×n identity matrix."""
        return Matrix([[1 if i == j else 0 for j in range(n)] for i in range(n)])

    @staticmethod
    def zeros(r, c):
        return Matrix([[0] * c for _ in range(r)])

    @staticmethod
    def ones(r, c):
        return Matrix([[1] * c for _ in range(r)])

    @staticmethod
    def diag(values):
        """Diagonal matrix from a list of values."""
        n = len(values)
        m = Matrix.zeros(n, n)
        for i, v in enumerate(values):
            m.rows[i][i] = v
        return m

    @staticmethod
    def hilbert(n):
        """n×n Hilbert matrix."""
        return Matrix([[1 / (i + j + 1) for j in range(n)] for i in range(n)])

    @staticmethod
    def vandermonde(vals, n=None):
        """Vandermonde matrix from values."""
        if n is None:
            n = len(vals)
        return Matrix([[v ** j for j in range(n)] for v in vals])

    # ── Display ─────────────────────────────────────────────────────────

    def __repr__(self):
        return f"Matrix({self.nrows}×{self.ncols})"

    def pretty(self, precision=4):
        """Pretty-print with aligned columns."""
        def fmt(x):
            if isinstance(x, float):
                if x == int(x):
                    return str(int(x))
                return f"{x:.{precision}g}"
            return str(x)

        formatted = [[fmt(x) for x in row] for row in self.rows]
        widths = [max(len(formatted[r][c]) for r in range(self.nrows))
                  for c in range(self.ncols)]
        lines = []
        for r in range(self.nrows):
            cells = [formatted[r][c].rjust(widths[c]) for c in range(self.ncols)]
            bracket = "│" if 0 < r < self.nrows - 1 else ("┌" if r == 0 else "└")
            bracket_r = "│" if 0 < r < self.nrows - 1 else ("┐" if r == 0 else "┘")
            lines.append(f"  {bracket} {' '.join(cells)} {bracket_r}")
        return "\n".join(lines)

    # ── Element access ──────────────────────────────────────────────────

    def get(self, r, c):
        return self.rows[r][c]

    def set(self, r, c, val):
        self.rows[r][c] = val

    def row(self, i):
        return list(self.rows[i])

    def col(self, j):
        return [self.rows[i][j] for i in range(self.nrows)]

    @property
    def shape(self):
        return (self.nrows, self.ncols)

    @property
    def is_square(self):
        return self.nrows == self.ncols

    # ── Arithmetic ──────────────────────────────────────────────────────

    def __add__(self, other):
        if isinstance(other, Matrix):
            if self.shape != other.shape:
                raise ValueError(f"Shape mismatch: {self.shape} vs {other.shape}")
            return Matrix([[self.rows[i][j] + other.rows[i][j]
                            for j in range(self.ncols)] for i in range(self.nrows)])
        return Matrix([[x + other for x in row] for row in self.rows])

    def __sub__(self, other):
        if isinstance(other, Matrix):
            if self.shape != other.shape:
                raise ValueError(f"Shape mismatch: {self.shape} vs {other.shape}")
            return Matrix([[self.rows[i][j] - other.rows[i][j]
                            for j in range(self.ncols)] for i in range(self.nrows)])
        return Matrix([[x - other for x in row] for row in self.rows])

    def __mul__(self, other):
        if isinstance(other, Matrix):
            return self._matmul(other)
        return Matrix([[x * other for x in row] for row in self.rows])

    def __rmul__(self, other):
        return self.__mul__(other)

    def __neg__(self):
        return self * (-1)

    def __pow__(self, n):
        if not self.is_square:
            raise ValueError("Power requires square matrix")
        if n == 0:
            return Matrix.identity(self.nrows)
        if n < 0:
            return self.inverse() ** (-n)
        result = Matrix.identity(self.nrows)
        base = self._copy()
        while n > 0:
            if n % 2 == 1:
                result = result * base
            base = base * base
            n //= 2
        return result

    def _matmul(self, other):
        if self.ncols != other.nrows:
            raise ValueError(f"Cannot multiply {self.shape} × {other.shape}")
        # Transpose other so the inner dot-product loop iterates rows
        # (contiguous lists) instead of columns (stride-ncols index lookups).
        # zip() paired iteration is ~30-40% faster than indexed sum() in
        # CPython for dense matrix multiply.
        other_T = [other.col(j) for j in range(other.ncols)]
        result = [[sum(a * b for a, b in zip(self_row, ot_col))
                   for ot_col in other_T] for self_row in self.rows]
        return Matrix(result)

    def _copy(self):
        return Matrix([row[:] for row in self.rows])

    # ── Transformations ─────────────────────────────────────────────────

    def transpose(self):
        return Matrix([[self.rows[i][j] for i in range(self.nrows)]
                       for j in range(self.ncols)])

    def trace(self):
        if not self.is_square:
            raise ValueError("Trace requires square matrix")
        return sum(self.rows[i][i] for i in range(self.nrows))

    def minor(self, row, col):
        """Sub-matrix excluding given row and column."""
        return Matrix([[self.rows[i][j] for j in range(self.ncols) if j != col]
                       for i in range(self.nrows) if i != row])

    # ── Determinant (Laplace expansion for small, LU for larger) ────────

    def det(self):
        if not self.is_square:
            raise ValueError("Determinant requires square matrix")
        n = self.nrows
        if n == 1:
            return self.rows[0][0]
        if n == 2:
            return self.rows[0][0] * self.rows[1][1] - self.rows[0][1] * self.rows[1][0]
        # LU-based for n >= 3
        m = [row[:] for row in self.rows]
        det_sign = 1
        for col in range(n):
            # Partial pivoting
            pivot = col
            for row in range(col + 1, n):
                if abs(m[row][col]) > abs(m[pivot][col]):
                    pivot = row
            if pivot != col:
                m[col], m[pivot] = m[pivot], m[col]
                det_sign *= -1
            if abs(m[col][col]) < 1e-14:
                return 0
            for row in range(col + 1, n):
                factor = m[row][col] / m[col][col]
                if factor == 0:
                    continue
                m_row = m[row]
                m_col = m[col]
                for k in range(col, n):
                    m_row[k] -= factor * m_col[k]
        result = det_sign
        for i in range(n):
            result *= m[i][i]
        return result

    # ── Inverse (Gauss-Jordan) ──────────────────────────────────────────

    def inverse(self):
        if not self.is_square:
            raise ValueError("Inverse requires square matrix")
        n = self.nrows
        # Augmented matrix [A | I]
        aug = [self.rows[i][:] + [1 if i == j else 0 for j in range(n)]
               for i in range(n)]
        for col in range(n):
            pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
            if abs(aug[pivot][col]) < 1e-14:
                raise ValueError("Matrix is singular, cannot invert")
            aug[col], aug[pivot] = aug[pivot], aug[col]
            pv = aug[col][col]
            aug[col] = [x / pv for x in aug[col]]
            for row in range(n):
                if row != col:
                    factor = aug[row][col]
                    if factor == 0:
                        continue
                    aug_col = aug[col]
                    aug_row = aug[row]
                    aug[row] = [aug_row[k] - factor * aug_col[k]
                                for k in range(2 * n)]
        return Matrix([row[n:] for row in aug])

    # ── Rank (via row echelon) ──────────────────────────────────────────

    def rank(self):
        m = [row[:] for row in self.rows]
        r, c = self.nrows, self.ncols
        rank = 0
        for col in range(c):
            pivot = None
            for row in range(rank, r):
                if abs(m[row][col]) > 1e-14:
                    pivot = row
                    break
            if pivot is None:
                continue
            m[rank], m[pivot] = m[pivot], m[rank]
            pv = m[rank][col]
            m[rank] = [x / pv for x in m[rank]]
            for row in range(r):
                if row != rank and abs(m[row][col]) > 1e-14:
                    factor = m[row][col]
                    m[row] = [m[row][k] - factor * m[rank][k] for k in range(c)]
            rank += 1
        return rank

    # ── Row Echelon Form ────────────────────────────────────────────────

    def rref(self):
        """Reduced Row Echelon Form."""
        m = [row[:] for row in self.rows]
        r, c = self.nrows, self.ncols
        pivot_row = 0
        for col in range(c):
            pivot = None
            for row in range(pivot_row, r):
                if abs(m[row][col]) > 1e-14:
                    pivot = row
                    break
            if pivot is None:
                continue
            m[pivot_row], m[pivot] = m[pivot], m[pivot_row]
            pv = m[pivot_row][col]
            m[pivot_row] = [x / pv for x in m[pivot_row]]
            for row in range(r):
                if row != pivot_row and abs(m[row][col]) > 1e-14:
                    factor = m[row][col]
                    m[row] = [m[row][k] - factor * m[pivot_row][k] for k in range(c)]
            pivot_row += 1
        # Clean near-zero
        for i in range(r):
            for j in range(c):
                if abs(m[i][j]) < 1e-12:
                    m[i][j] = 0
        return Matrix(m)

    # ── Solve Ax = b ────────────────────────────────────────────────────

    def solve(self, b):
        """Solve Ax = b using Gaussian elimination with back-substitution."""
        if not self.is_square:
            raise ValueError("Solve requires square coefficient matrix")
        n = self.nrows
        if len(b) != n:
            raise ValueError(f"b has {len(b)} entries but matrix is {n}×{n}")
        aug = [self.rows[i][:] + [b[i]] for i in range(n)]
        for col in range(n):
            pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
            if abs(aug[pivot][col]) < 1e-14:
                raise ValueError("System has no unique solution")
            aug[col], aug[pivot] = aug[pivot], aug[col]
            for row in range(col + 1, n):
                factor = aug[row][col] / aug[col][col]
                for k in range(col, n + 1):
                    aug[row][k] -= factor * aug[col][k]
        # Back-substitution
        x = [0.0] * n
        for i in range(n - 1, -1, -1):
            x[i] = (aug[i][n] - sum(aug[i][j] * x[j] for j in range(i + 1, n))) / aug[i][i]
        return x

    # ── LU Decomposition ───────────────────────────────────────────────

    def lu(self):
        """LU decomposition (Doolittle). Returns (L, U)."""
        if not self.is_square:
            raise ValueError("LU requires square matrix")
        n = self.nrows
        L = [[0.0] * n for _ in range(n)]
        U = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(i, n):
                U[i][j] = self.rows[i][j] - sum(L[i][k] * U[k][j] for k in range(i))
            for j in range(i, n):
                if i == j:
                    L[i][i] = 1.0
                else:
                    if abs(U[i][i]) < 1e-14:
                        raise ValueError("LU decomposition failed (zero pivot)")
                    L[j][i] = (self.rows[j][i] - sum(L[j][k] * U[k][i] for k in range(i))) / U[i][i]
        return Matrix(L), Matrix(U)

    # ── QR Decomposition (Gram-Schmidt) ─────────────────────────────────

    def qr(self):
        """QR decomposition via modified Gram-Schmidt. Returns (Q, R)."""
        if self.nrows < self.ncols:
            raise ValueError("QR requires nrows >= ncols")
        cols = [[self.rows[i][j] for i in range(self.nrows)] for j in range(self.ncols)]
        q_cols = []
        R = [[0.0] * self.ncols for _ in range(self.ncols)]
        for j in range(self.ncols):
            v = cols[j][:]
            for i in range(len(q_cols)):
                R[i][j] = sum(q_cols[i][k] * v[k] for k in range(self.nrows))
                v = [v[k] - R[i][j] * q_cols[i][k] for k in range(self.nrows)]
            norm = math.sqrt(sum(x * x for x in v))
            if norm < 1e-14:
                raise ValueError("Matrix columns are linearly dependent")
            R[j][j] = norm
            q_cols.append([x / norm for x in v])
        Q = Matrix([[q_cols[j][i] for j in range(self.ncols)] for i in range(self.nrows)])
        return Q, Matrix(R)

    # ── Eigenvalues (QR algorithm for small matrices) ──────────────────

    def eigenvalues(self, iterations=200):
        """Approximate eigenvalues using QR iteration."""
        if not self.is_square:
            raise ValueError("Eigenvalues require square matrix")
        A = self._copy()
        n = self.nrows
        for _ in range(iterations):
            try:
                Q, R = A.qr()
                A = R * Q
            except ValueError:
                break
        eigs = [A.rows[i][i] for i in range(n)]
        # Clean near-zero imaginary artifacts
        eigs = [round(e, 10) if isinstance(e, float) else e for e in eigs]
        return sorted(eigs, key=lambda x: -abs(x))

    # ── Norms ───────────────────────────────────────────────────────────

    def norm_frobenius(self):
        return math.sqrt(sum(x * x for row in self.rows for x in row))

    def norm_inf(self):
        return max(sum(abs(x) for x in row) for row in self.rows)

    def norm_1(self):
        return max(sum(abs(self.rows[i][j]) for i in range(self.nrows))
                   for j in range(self.ncols))

    # ── Condition Number ────────────────────────────────────────────────

    def cond(self):
        """Condition number (using Frobenius norm)."""
        return self.norm_frobenius() * self.inverse().norm_frobenius()

    # ── Element-wise operations ─────────────────────────────────────────

    def apply(self, fn):
        """Apply a function element-wise."""
        return Matrix([[fn(x) for x in row] for row in self.rows])

    def hadamard(self, other):
        """Element-wise (Hadamard) product."""
        if self.shape != other.shape:
            raise ValueError("Shape mismatch for Hadamard product")
        return Matrix([[self.rows[i][j] * other.rows[i][j]
                        for j in range(self.ncols)] for i in range(self.nrows)])

    # ── Augment / Stack ─────────────────────────────────────────────────

    def augment(self, other):
        """Horizontal concatenation."""
        if self.nrows != other.nrows:
            raise ValueError("Row count mismatch")
        return Matrix([self.rows[i] + other.rows[i] for i in range(self.nrows)])

    def vstack(self, other):
        """Vertical concatenation."""
        if self.ncols != other.ncols:
            raise ValueError("Column count mismatch")
        return Matrix(self.rows + other.rows)


# ── REPL ────────────────────────────────────────────────────────────────────

HELP_TEXT = """
╔══════════════════════════════════════════════════════════════╗
║              sauravmatrix — Matrix Calculator               ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  CREATE MATRICES                                             ║
║    A = [[1,2],[3,4]]          Define from literal            ║
║    B = eye(3)                 3×3 identity                   ║
║    C = zeros(2,3)             2×3 zero matrix                ║
║    D = ones(3,2)              3×2 ones matrix                ║
║    E = diag(1,2,3)            Diagonal matrix                ║
║    F = hilbert(4)             4×4 Hilbert matrix             ║
║    G = vander(1,2,3)          Vandermonde matrix             ║
║                                                              ║
║  ARITHMETIC                                                  ║
║    A + B    A - B    A * B    Matrix operations               ║
║    A * 3    3 * A             Scalar multiplication           ║
║    A ^ 2    A ^ -1            Power / inverse                 ║
║                                                              ║
║  OPERATIONS                                                  ║
║    det(A)                     Determinant                    ║
║    inv(A)                     Inverse                        ║
║    trans(A)  or  A'           Transpose                      ║
║    trace(A)                   Trace                          ║
║    rank(A)                    Rank                           ║
║    rref(A)                    Reduced row echelon form       ║
║    lu(A)                      LU decomposition               ║
║    qr(A)                      QR decomposition               ║
║    eig(A)                     Eigenvalues                    ║
║    solve(A, [1,2,3])          Solve Ax = b                   ║
║    norm(A)                    Frobenius norm                 ║
║    cond(A)                    Condition number               ║
║                                                              ║
║  COMMANDS                                                    ║
║    show      List stored matrices                            ║
║    clear     Clear all matrices                              ║
║    demo      Run demos                                       ║
║    help      Show this help                                  ║
║    quit      Exit                                            ║
╚══════════════════════════════════════════════════════════════╝
"""


def _parse_matrix_literal(s):
    """Parse [[1,2],[3,4]] into Matrix."""
    s = s.strip()
    try:
        data = ast.literal_eval(s)
        if isinstance(data, list) and data and isinstance(data[0], list):
            return Matrix([[float(x) for x in row] for row in data])
    except Exception:
        pass
    return None


def run_demo():
    """Run demonstration of matrix operations."""
    print("\n═══ sauravmatrix Demo ═══\n")

    print("1) Creating a 3×3 matrix A:")
    A = Matrix([[1, 2, 3], [4, 5, 6], [7, 8, 10]])
    print(A.pretty())

    print(f"\n2) Determinant: det(A) = {A.det()}")
    print(f"\n3) Trace: trace(A) = {A.trace()}")
    print(f"\n4) Rank: rank(A) = {A.rank()}")

    print("\n5) Transpose:")
    print(A.transpose().pretty())

    print("\n6) Inverse:")
    print(A.inverse().pretty())

    print("\n7) A × A⁻¹ = I (verification):")
    print((A * A.inverse()).pretty())

    print("\n8) LU Decomposition:")
    L, U = A.lu()
    print("  L:")
    print(L.pretty())
    print("  U:")
    print(U.pretty())

    print("\n9) Solving Ax = [1, 2, 3]:")
    x = A.solve([1, 2, 3])
    print(f"  x = [{', '.join(f'{v:.4g}' for v in x)}]")

    print("\n10) Eigenvalues:")
    eigs = A.eigenvalues()
    print(f"  λ = [{', '.join(f'{v:.4g}' for v in eigs)}]")

    print("\n11) 4×4 Hilbert matrix (ill-conditioned):")
    H = Matrix.hilbert(4)
    print(H.pretty())
    print(f"  Condition number: {H.cond():.2f}")

    print("\n12) Matrix power A³:")
    print((A ** 3).pretty())

    print()


class REPL:
    """Interactive matrix calculator REPL."""

    def __init__(self):
        self.vars = {}

    def eval_expr(self, expr):
        """Evaluate a matrix expression string."""
        expr = expr.strip()
        if not expr:
            return None

        # Assignment: X = ...
        m = re.match(r'^([A-Za-z_]\w*)\s*=\s*(.+)$', expr)
        if m:
            name, rhs = m.group(1), m.group(2)
            result = self.eval_expr(rhs)
            if result is not None:
                self.vars[name] = result
                if isinstance(result, Matrix):
                    print(result.pretty())
                else:
                    print(f"  = {result}")
            return None

        # Commands
        if expr == 'help':
            print(HELP_TEXT)
            return None
        if expr == 'show':
            if not self.vars:
                print("  (no matrices stored)")
            for k, v in self.vars.items():
                if isinstance(v, Matrix):
                    print(f"  {k}: {v.nrows}×{v.ncols}")
                else:
                    print(f"  {k}: {v}")
            return None
        if expr == 'clear':
            self.vars.clear()
            print("  Cleared all matrices.")
            return None
        if expr == 'demo':
            run_demo()
            return None

        # Transpose shorthand: A'
        if expr.endswith("'") and expr[:-1].strip() in self.vars:
            mat = self.vars[expr[:-1].strip()]
            if isinstance(mat, Matrix):
                result = mat.transpose()
                print(result.pretty())
                return result

        # Functions
        func_match = re.match(r'^(\w+)\((.+)\)$', expr)
        if func_match:
            fn_name = func_match.group(1)
            args_str = func_match.group(2)
            return self._eval_function(fn_name, args_str)

        # Matrix literal
        mat = _parse_matrix_literal(expr)
        if mat:
            print(mat.pretty())
            return mat

        # Binary ops: A + B, A * B, A * 3, A ^ 2, etc.
        for op in ['+', '-', '*', '^']:
            # Split on operator (not inside brackets)
            parts = self._split_op(expr, op)
            if parts:
                left, right = parts
                lv = self._resolve(left.strip())
                rv = self._resolve(right.strip())
                if lv is not None and rv is not None:
                    if op == '+':
                        result = lv + rv
                    elif op == '-':
                        result = lv - rv
                    elif op == '*':
                        result = lv * rv
                    elif op == '^':
                        result = lv ** int(rv) if not isinstance(rv, Matrix) else None
                    if result is not None:
                        if isinstance(result, Matrix):
                            print(result.pretty())
                        else:
                            print(f"  = {result}")
                        return result

        # Variable lookup
        if expr in self.vars:
            v = self.vars[expr]
            if isinstance(v, Matrix):
                print(v.pretty())
            else:
                print(f"  = {v}")
            return v

        print(f"  ✗ Cannot parse: {expr}")
        return None

    def _split_op(self, expr, op):
        """Split expression on operator, respecting brackets."""
        depth = 0
        # Search from right for left-associativity
        for i in range(len(expr) - 1, -1, -1):
            if expr[i] in '([':
                depth += 1
            elif expr[i] in ')]':
                depth -= 1
            elif expr[i] == op and depth == 0 and i > 0:
                return expr[:i], expr[i + 1:]
        return None

    def _resolve(self, token):
        """Resolve a token to a value (matrix, number, or variable)."""
        token = token.strip()
        if token in self.vars:
            return self.vars[token]
        try:
            return float(token) if '.' in token else int(token)
        except ValueError:
            pass
        mat = _parse_matrix_literal(token)
        if mat:
            return mat
        return None

    def _eval_function(self, name, args_str):
        """Evaluate a function call."""
        if name == 'eye':
            n = int(args_str.strip())
            result = Matrix.identity(n)
            print(result.pretty())
            return result
        if name == 'zeros':
            parts = [int(x.strip()) for x in args_str.split(',')]
            result = Matrix.zeros(*parts)
            print(result.pretty())
            return result
        if name == 'ones':
            parts = [int(x.strip()) for x in args_str.split(',')]
            result = Matrix.ones(*parts)
            print(result.pretty())
            return result
        if name == 'diag':
            vals = [float(x.strip()) for x in args_str.split(',')]
            result = Matrix.diag(vals)
            print(result.pretty())
            return result
        if name == 'hilbert':
            n = int(args_str.strip())
            result = Matrix.hilbert(n)
            print(result.pretty())
            return result
        if name == 'vander':
            vals = [float(x.strip()) for x in args_str.split(',')]
            result = Matrix.vandermonde(vals)
            print(result.pretty())
            return result

        # Unary matrix functions
        arg = self._resolve(args_str)
        if isinstance(arg, Matrix):
            if name == 'det':
                d = arg.det()
                print(f"  = {d}")
                return d
            if name == 'inv':
                result = arg.inverse()
                print(result.pretty())
                return result
            if name == 'trans':
                result = arg.transpose()
                print(result.pretty())
                return result
            if name == 'trace':
                t = arg.trace()
                print(f"  = {t}")
                return t
            if name == 'rank':
                r = arg.rank()
                print(f"  = {r}")
                return r
            if name == 'rref':
                result = arg.rref()
                print(result.pretty())
                return result
            if name == 'norm':
                n = arg.norm_frobenius()
                print(f"  = {n:.6g}")
                return n
            if name == 'cond':
                c = arg.cond()
                print(f"  = {c:.6g}")
                return c
            if name == 'lu':
                L, U = arg.lu()
                print("  L:")
                print(L.pretty())
                print("  U:")
                print(U.pretty())
                return L
            if name == 'qr':
                Q, R = arg.qr()
                print("  Q:")
                print(Q.pretty())
                print("  R:")
                print(R.pretty())
                return Q
            if name == 'eig':
                eigs = arg.eigenvalues()
                print(f"  λ = [{', '.join(f'{v:.6g}' for v in eigs)}]")
                return eigs

        # solve(A, [b1, b2, ...])
        if name == 'solve':
            # Parse: A, [1,2,3]
            bracket = args_str.find('[')
            if bracket > 0:
                mat_name = args_str[:bracket].rstrip(', ')
                b_str = args_str[bracket:]
                mat = self._resolve(mat_name)
                try:
                    b = ast.literal_eval(b_str)
                    b = [float(x) for x in b]
                except Exception:
                    print("  ✗ Cannot parse b vector")
                    return None
                if isinstance(mat, Matrix):
                    x = mat.solve(b)
                    print(f"  x = [{', '.join(f'{v:.6g}' for v in x)}]")
                    return x

        print(f"  ✗ Unknown function: {name}")
        return None

    def run(self):
        """Run the interactive REPL."""
        print("╔══════════════════════════════════════════╗")
        print("║   sauravmatrix — Matrix Calculator       ║")
        print("║   Type 'help' for commands, 'quit' to    ║")
        print("║   exit. Part of the sauravcode ecosystem. ║")
        print("╚══════════════════════════════════════════╝")
        print()

        while True:
            try:
                line = input("matrix> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye!")
                break
            if not line:
                continue
            if line in ('quit', 'exit', 'q'):
                print("Bye!")
                break
            try:
                self.eval_expr(line)
            except Exception as e:
                print(f"  ✗ Error: {e}")


def main():
    args = sys.argv[1:]
    if '--demo' in args:
        run_demo()
        return
    if '--eval' in args:
        idx = args.index('--eval')
        if idx + 1 < len(args):
            repl = REPL()
            repl.eval_expr(args[idx + 1])
            return
    if '--help' in args or '-h' in args:
        print(__doc__)
        return
    repl = REPL()
    repl.run()


if __name__ == '__main__':
    main()
