
def format_number(value):
    return f"{value:,}"


def truncate(text, length=50):
    if len(text) <= length:
        return text
    return text[:length] + "..."
