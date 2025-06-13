import re
from pageql.parser import parsefirstword
from pageql.database import parse_param_attrs
from pageql.reactive import ReadOnly


def handle_param(node_content: str, params: dict) -> tuple[str, object | None]:
    """Validate a ``#param`` directive and return its name and value."""
    param_name, attrs_str = parsefirstword(node_content)
    param_name = param_name.replace('.', '__')
    attrs = parse_param_attrs(attrs_str)

    is_required = attrs.get('required', not attrs.__contains__('optional'))
    param_value = params.get(param_name)
    if isinstance(param_value, ReadOnly):
        param_value = param_value.value

    if param_value is None:
        if 'default' in attrs:
            param_value = attrs['default']
            is_required = False
        elif is_required:
            raise ValueError(f"Required parameter '{param_name}' is missing")

    if param_value is not None:
        param_type = attrs.get('type', 'string')
        try:
            if param_type == 'integer':
                param_value = int(param_value)
            elif param_type == 'float':
                param_value = float(param_value)
            elif param_type == 'boolean':
                param_value = bool(param_value) and str(param_value).lower() not in ['0', 'false', '']
            else:
                param_value = str(param_value)

            if param_type == 'string' and 'minlength' in attrs:
                minlen = int(attrs['minlength'])
                if len(param_value) < minlen:
                    raise ValueError(
                        f"Parameter '{param_name}' length {len(param_value)} is less than minlength {minlen}."
                    )
            if param_type == 'string' and 'maxlength' in attrs:
                maxlen = int(attrs['maxlength'])
                if len(param_value) > maxlen:
                    raise ValueError(
                        f"Parameter '{param_name}' length {len(param_value)} is greater than maxlength {maxlen}."
                    )
            if param_type == 'string' and 'pattern' in attrs:
                pattern = attrs['pattern']
                if not re.match(pattern, param_value):
                    raise ValueError(
                        f"Parameter '{param_name}' does not match pattern '{pattern}'."
                    )
            if param_type in ('integer', 'float') and 'min' in attrs:
                minval = float(attrs['min']) if param_type == 'float' else int(attrs['min'])
                if param_value < minval:
                    raise ValueError(
                        f"Parameter '{param_name}' value {param_value} is less than min {minval}."
                    )
            if param_type in ('integer', 'float') and 'max' in attrs:
                maxval = float(attrs['max']) if param_type == 'float' else int(attrs['max'])
                if param_value > maxval:
                    raise ValueError(
                        f"Parameter '{param_name}' value {param_value} is greater than max {maxval}."
                    )
            if param_type == 'boolean' and 'required' in attrs:
                if param_value is None:
                    raise ValueError(
                        f"Parameter '{param_name}' is required but was not provided."
                    )
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"Parameter '{param_name}' failed type/validation '{param_type}': {e}"
            )

    return param_name, param_value
