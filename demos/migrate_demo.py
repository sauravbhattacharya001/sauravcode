# migrate_demo.py — Sample Python to convert to sauravcode
# This demonstrates what sauravmigrate can handle

def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)

# Print first 10 fibonacci numbers
for i in range(10):
    result = fibonacci(i)
    print(f"fib({i}) = {result}")

# List operations
numbers = [1, 2, 3, 4, 5]
total = 0
for n in numbers:
    total = total + n
print(f"Sum: {total}")

# Error handling
def safe_divide(a, b):
    if b == 0:
        raise Exception("Cannot divide by zero")
    return a / b

try:
    answer = safe_divide(10, 0)
except Exception as e:
    print(f"Error: {e}")

answer = safe_divide(10, 2)
print(f"10 / 2 = {answer}")
