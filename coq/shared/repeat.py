from .types import Edit, RangeEdit, SnippetEdit, SnippetRangeEdit


def sanitize(edit: Edit) -> Edit:
    if isinstance(edit, SnippetRangeEdit):
        return (
            SnippetEdit(grammar=edit.grammar, new_text=edit.new_text)
            if edit.fallback == edit.new_text
            else Edit(new_text=edit.fallback)
        )
    elif isinstance(edit, SnippetEdit):
        return edit
    elif isinstance(edit, RangeEdit):
        return Edit(new_text=edit.fallback)
    else:
        return Edit(new_text=edit.new_text)
