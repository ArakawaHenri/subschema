
class _UnsupportedCaseError(Exception):
    pass


class _CanonicalizationError(_UnsupportedCaseError):
    pass


class _SubtypeCheckError(_UnsupportedCaseError):
    pass


class UnsupportedRecursiveRefError(_CanonicalizationError):
    def __init__(self, schema, which_side):
        self.schema = schema
        self.which_side = which_side

    def __str__(self):
        return f"Recursive schemas are not supported. {self.which_side} is recursive."


class UnknownDialectError(_CanonicalizationError):
    def __init__(self, dialect):
        self.dialect = dialect

    def __str__(self):
        return f"Unknown JSON Schema dialect: {self.dialect!r}."


class ConflictingDialectError(_CanonicalizationError):
    def __init__(self, dialects):
        self.dialects = dialects

    def __str__(self):
        dialects = ", ".join(str(dialect) for dialect in self.dialects)
        return f"Conflicting JSON Schema dialect declarations: {dialects}."


class UnsupportedKeywordError(_CanonicalizationError):
    def __init__(self, keyword, dialect, path=()):
        self.keyword = keyword
        self.dialect = dialect
        self.path = path

    def __str__(self):
        path = "/".join(self.path) if self.path else "<root>"
        return (
            f"JSON Schema keyword {self.keyword!r} at {path} is not supported "
            f"by subschema for selected dialect {self.dialect} yet."
        )


class UnsupportedEnumCanonicalizationError(_CanonicalizationError):
    def __init__(self, tau, schema):
        self.tau = tau
        self.schema = schema

    def __str__(self):
        return f"Canonicalizing an enum schema of type {self.tau} is not supported."


class UnsupportedNegatedObjectError(_SubtypeCheckError):
    def __init__(self, schema):
        self.schema = schema

    def __str__(self):
        return f"Object negation at {self.schema} is not supported."


class UnsupportedNegatedArrayError(_SubtypeCheckError):
    def __init__(self, schema):
        self.schema = schema

    def __str__(self):
        return f"Array negation at {self.schema} is not supported."


# class UnsupportedSchemaType(_Error):
#     '''
#     Probably this is not required since custom types are not
#     supported by jsonschema validation anyways; so we will not reat
#     a case that uses this exception.'''

#     def __init__(self, schema, tau):
#         self.schema = schema
#         self.tau = tau

#     def __str__(self):
# return '{} is unsupported jsonschema type in schema:
# {}'.format(self.tau, self.schema)

# class UnsupportedSubtypeChecker(_Error):

#     def __init__(self, schema, desc):
#         self.schema = schema
#         self.desc = desc

#     def __str__(self):
#         return '{} is unsupported. Schema: {}'.format(self.desc, self.schema)
