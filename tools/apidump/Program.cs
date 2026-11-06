// apidump: print the public (and optionally protected) API surface of .NET
// assemblies as greppable text, using only System.Reflection.Metadata from
// the runtime. Nothing is loaded or executed.
//
//   apidump [--all] [--out DIR] <file.dll | directory> ...
//
// With --out, one <assembly>.txt per input; otherwise everything goes to stdout.
// --all includes private and internal members.

using System.Collections.Immutable;
using System.Reflection;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Text;

var inputs = new List<string>();
string? outDir = null;
bool all = false;
for (int i = 0; i < args.Length; i++)
{
    switch (args[i])
    {
        case "--all": all = true; break;
        case "--out": outDir = args[++i]; break;
        case "-h": case "--help": Usage(); return 0;
        default: inputs.Add(args[i]); break;
    }
}
if (inputs.Count == 0) { Usage(); return 2; }

var files = new List<string>();
foreach (var input in inputs)
{
    if (Directory.Exists(input))
        files.AddRange(Directory.EnumerateFiles(input, "*.dll").OrderBy(f => f, StringComparer.Ordinal));
    else if (File.Exists(input))
        files.Add(input);
    else { Console.Error.WriteLine($"apidump: not found: {input}"); return 1; }
}
if (outDir != null) Directory.CreateDirectory(outDir);

int failures = 0;
foreach (var file in files)
{
    try
    {
        var text = Dump(file, all);
        if (outDir == null) Console.Out.Write(text);
        else File.WriteAllText(Path.Combine(outDir, Path.GetFileNameWithoutExtension(file) + ".txt"), text);
    }
    catch (Exception e) when (e is BadImageFormatException || e is InvalidOperationException)
    {
        Console.Error.WriteLine($"apidump: skipped {Path.GetFileName(file)}: not a managed assembly ({e.GetType().Name})");
        failures++;
    }
}
return failures == 0 ? 0 : 1;

static void Usage() =>
    Console.Error.WriteLine("usage: apidump [--all] [--out DIR] <file.dll | directory> ...");

static string Dump(string path, bool all)
{
    using var stream = File.OpenRead(path);
    using var pe = new PEReader(stream);
    if (!pe.HasMetadata) throw new BadImageFormatException("no CLI metadata");
    var md = pe.GetMetadataReader();
    var sb = new StringBuilder();
    var asm = md.GetAssemblyDefinition();
    sb.Append("assembly ").Append(md.GetString(asm.Name)).Append(' ').Append(asm.Version)
      .Append("  file ").Append(Path.GetFileName(path)).Append('\n');
    var sig = new SigProvider(md);

    foreach (var th in md.TypeDefinitions)
    {
        var t = md.GetTypeDefinition(th);
        var name = md.GetString(t.Name);
        if (name.StartsWith('<')) continue;                    // compiler-generated
        var attrs = t.Attributes;
        bool nested = t.GetDeclaringType() != default;
        if (!all && !IsTypeVisible(md, t)) continue;

        string kind =
            (attrs & TypeAttributes.Interface) != 0 ? "interface" :
            IsEnum(md, t) ? "enum" :
            IsValueType(md, t) ? "struct" :
            IsDelegate(md, t) ? "delegate" : "class";
        string vis = (attrs & TypeAttributes.VisibilityMask) switch
        {
            TypeAttributes.Public or TypeAttributes.NestedPublic => "public",
            TypeAttributes.NestedFamily => "protected",
            TypeAttributes.NestedFamORAssem => "protected internal",
            TypeAttributes.NestedPrivate => "private",
            _ => "internal",
        };
        string mods = "";
        if (kind == "class")
        {
            if ((attrs & TypeAttributes.Abstract) != 0 && (attrs & TypeAttributes.Sealed) != 0) mods = " static";
            else if ((attrs & TypeAttributes.Abstract) != 0) mods = " abstract";
            else if ((attrs & TypeAttributes.Sealed) != 0) mods = " sealed";
        }
        var full = FullTypeName(md, t);
        sb.Append('\n').Append(vis).Append(mods).Append(' ').Append(kind).Append(' ').Append(full);
        var gp = t.GetGenericParameters();
        if (gp.Count > 0) sb.Append('<').Append(string.Join(", ", gp.Select(h => md.GetString(md.GetGenericParameter(h).Name)))).Append('>');

        var bases = new List<string>();
        if (!t.BaseType.IsNil)
        {
            var b = sig.TypeName(t.BaseType);
            if (b != "System.Object" && !(kind == "enum" && b == "System.Enum") && !(kind == "struct" && b == "System.ValueType"))
                bases.Add(b);
        }
        foreach (var ih in t.GetInterfaceImplementations())
            bases.Add(sig.TypeName(md.GetInterfaceImplementation(ih).Interface));
        if (bases.Count > 0) sb.Append(" : ").Append(string.Join(", ", bases));
        sb.Append('\n');

        if (kind == "enum")
        {
            foreach (var fh in t.GetFields())
            {
                var f = md.GetFieldDefinition(fh);
                if ((f.Attributes & FieldAttributes.Literal) == 0) continue;
                var c = md.GetConstant(f.GetDefaultValue());
                sb.Append("    ").Append(md.GetString(f.Name)).Append(" = ").Append(ReadConstant(md, c)).Append('\n');
            }
            continue;
        }

        foreach (var fh in t.GetFields())
        {
            var f = md.GetFieldDefinition(fh);
            if (!all && !IsFieldVisible(f.Attributes & FieldAttributes.FieldAccessMask)) continue;
            var fvis = FieldVis(f.Attributes);
            string fmods = (f.Attributes & FieldAttributes.Literal) != 0 ? " const" :
                           (f.Attributes & FieldAttributes.Static) != 0 ? " static" : "";
            if ((f.Attributes & FieldAttributes.InitOnly) != 0) fmods += " readonly";
            var ft = f.DecodeSignature(sig, null);
            sb.Append("    ").Append(fvis).Append(fmods).Append(" field ").Append(ft).Append(' ').Append(md.GetString(f.Name)).Append('\n');
        }

        // Properties and events, so get_/set_/add_/remove_ pairs read naturally.
        var accessorMethods = new HashSet<MethodDefinitionHandle>();
        foreach (var ph in t.GetProperties())
        {
            var p = md.GetPropertyDefinition(ph);
            var acc = p.GetAccessors();
            var parts = new List<string>();
            MethodAttributes best = 0;
            if (!acc.Getter.IsNil) { accessorMethods.Add(acc.Getter); var g = md.GetMethodDefinition(acc.Getter); if (all || IsVisible(g.Attributes & MethodAttributes.MemberAccessMask)) { parts.Add($"{MethodVisShort(g.Attributes)}get"); best = Max(best, g.Attributes); } }
            if (!acc.Setter.IsNil) { accessorMethods.Add(acc.Setter); var s = md.GetMethodDefinition(acc.Setter); if (all || IsVisible(s.Attributes & MethodAttributes.MemberAccessMask)) { parts.Add($"{MethodVisShort(s.Attributes)}set"); best = Max(best, s.Attributes); } }
            if (parts.Count == 0) continue;
            var psig = p.DecodeSignature(sig, null);
            string stat = (best & MethodAttributes.Static) != 0 ? " static" : "";
            sb.Append("    ").Append(MethodVis(best)).Append(stat).Append(" property ").Append(psig.ReturnType).Append(' ').Append(md.GetString(p.Name));
            if (psig.ParameterTypes.Length > 0) sb.Append('[').Append(string.Join(", ", psig.ParameterTypes)).Append(']');
            sb.Append(" { ").Append(string.Join("; ", parts)).Append("; }\n");
        }
        foreach (var eh in t.GetEvents())
        {
            var e = md.GetEventDefinition(eh);
            var acc = e.GetAccessors();
            MethodAttributes best = 0;
            if (!acc.Adder.IsNil) { accessorMethods.Add(acc.Adder); best = Max(best, md.GetMethodDefinition(acc.Adder).Attributes); }
            if (!acc.Remover.IsNil) { accessorMethods.Add(acc.Remover); best = Max(best, md.GetMethodDefinition(acc.Remover).Attributes); }
            if (!acc.Raiser.IsNil) accessorMethods.Add(acc.Raiser);
            if (!all && !IsVisible(best & MethodAttributes.MemberAccessMask)) continue;
            sb.Append("    ").Append(MethodVis(best)).Append(" event ").Append(sig.TypeName(e.Type)).Append(' ').Append(md.GetString(e.Name)).Append('\n');
        }

        foreach (var mh in t.GetMethods())
        {
            if (accessorMethods.Contains(mh)) continue;
            var m = md.GetMethodDefinition(mh);
            if (!all && !IsVisible(m.Attributes & MethodAttributes.MemberAccessMask)) continue;
            var mname = md.GetString(m.Name);
            if (mname == ".cctor") continue;
            var msig = m.DecodeSignature(sig, null);
            string mmods = "";
            if ((m.Attributes & MethodAttributes.Static) != 0) mmods += " static";
            if ((m.Attributes & MethodAttributes.Abstract) != 0 && kind != "interface") mmods += " abstract";
            else if ((m.Attributes & MethodAttributes.Virtual) != 0 && kind != "interface")
                mmods += (m.Attributes & MethodAttributes.NewSlot) != 0 ? " virtual" : " override";
            var pnames = m.GetParameters().Select(ph => md.GetParameter(ph)).Where(p => p.SequenceNumber > 0)
                          .OrderBy(p => p.SequenceNumber).Select(p => md.GetString(p.Name)).ToList();
            var ps = new List<string>();
            for (int i = 0; i < msig.ParameterTypes.Length; i++)
                ps.Add(msig.ParameterTypes[i] + (i < pnames.Count ? " " + pnames[i] : ""));
            sb.Append("    ").Append(MethodVis(m.Attributes)).Append(mmods).Append(' ');
            if (mname == ".ctor") sb.Append("ctor ").Append(name);
            else
            {
                sb.Append(msig.ReturnType).Append(' ').Append(mname);
                var mgp = m.GetGenericParameters();
                if (mgp.Count > 0) sb.Append('<').Append(string.Join(", ", mgp.Select(h => md.GetString(md.GetGenericParameter(h).Name)))).Append('>');
            }
            sb.Append('(').Append(string.Join(", ", ps)).Append(")\n");
        }
    }
    return sb.ToString();
}

static MethodAttributes Max(MethodAttributes a, MethodAttributes b) =>
    Rank(b & MethodAttributes.MemberAccessMask) > Rank(a & MethodAttributes.MemberAccessMask) ? b : a;
static int Rank(MethodAttributes access) => access switch
{
    MethodAttributes.Public => 5, MethodAttributes.FamORAssem => 4, MethodAttributes.Family => 3,
    MethodAttributes.Assembly => 2, MethodAttributes.FamANDAssem => 1, _ => 0,
};
static bool IsVisible(MethodAttributes access) => Rank(access) >= 3;
static bool IsFieldVisible(FieldAttributes access) => access is FieldAttributes.Public or FieldAttributes.Family or FieldAttributes.FamORAssem;
static string MethodVis(MethodAttributes a) => (a & MethodAttributes.MemberAccessMask) switch
{
    MethodAttributes.Public => "public", MethodAttributes.Family => "protected",
    MethodAttributes.FamORAssem => "protected internal", MethodAttributes.Assembly => "internal",
    MethodAttributes.FamANDAssem => "private protected", _ => "private",
};
static string MethodVisShort(MethodAttributes a) => (a & MethodAttributes.MemberAccessMask) == MethodAttributes.Public ? "" : MethodVis(a) + " ";
static string FieldVis(FieldAttributes a) => (a & FieldAttributes.FieldAccessMask) switch
{
    FieldAttributes.Public => "public", FieldAttributes.Family => "protected",
    FieldAttributes.FamORAssem => "protected internal", FieldAttributes.Assembly => "internal",
    FieldAttributes.FamANDAssem => "private protected", _ => "private",
};

static bool IsTypeVisible(MetadataReader md, TypeDefinition t)
{
    var v = t.Attributes & TypeAttributes.VisibilityMask;
    if (v == TypeAttributes.Public) return true;
    if (v is TypeAttributes.NestedPublic or TypeAttributes.NestedFamily or TypeAttributes.NestedFamORAssem)
        return IsTypeVisible(md, md.GetTypeDefinition(t.GetDeclaringType()));
    return false;
}
static string FullTypeName(MetadataReader md, TypeDefinition t)
{
    var name = md.GetString(t.Name);
    var decl = t.GetDeclaringType();
    if (!decl.IsNil) return FullTypeName(md, md.GetTypeDefinition(decl)) + "." + name;
    var ns = md.GetString(t.Namespace);
    return ns.Length == 0 ? name : ns + "." + name;
}
static string BaseName(MetadataReader md, TypeDefinition t)
{
    if (t.BaseType.IsNil) return "";
    return t.BaseType.Kind switch
    {
        HandleKind.TypeReference => QualifiedRef(md, md.GetTypeReference((TypeReferenceHandle)t.BaseType)),
        HandleKind.TypeDefinition => FullTypeName(md, md.GetTypeDefinition((TypeDefinitionHandle)t.BaseType)),
        _ => "",
    };
}
static string QualifiedRef(MetadataReader md, TypeReference r)
{
    var name = md.GetString(r.Name);
    if (r.ResolutionScope.Kind == HandleKind.TypeReference)
        return QualifiedRef(md, md.GetTypeReference((TypeReferenceHandle)r.ResolutionScope)) + "." + name;
    var ns = md.GetString(r.Namespace);
    return ns.Length == 0 ? name : ns + "." + name;
}
static bool IsEnum(MetadataReader md, TypeDefinition t) => BaseName(md, t) == "System.Enum";
static bool IsValueType(MetadataReader md, TypeDefinition t) => BaseName(md, t) == "System.ValueType";
static bool IsDelegate(MetadataReader md, TypeDefinition t) => BaseName(md, t) is "System.MulticastDelegate" or "System.Delegate";

static string ReadConstant(MetadataReader md, Constant c)
{
    var r = md.GetBlobReader(c.Value);
    return c.TypeCode switch
    {
        ConstantTypeCode.Int32 => r.ReadInt32().ToString(),
        ConstantTypeCode.UInt32 => r.ReadUInt32().ToString(),
        ConstantTypeCode.Int64 => r.ReadInt64().ToString(),
        ConstantTypeCode.UInt64 => r.ReadUInt64().ToString(),
        ConstantTypeCode.Int16 => r.ReadInt16().ToString(),
        ConstantTypeCode.UInt16 => r.ReadUInt16().ToString(),
        ConstantTypeCode.Byte => r.ReadByte().ToString(),
        ConstantTypeCode.SByte => r.ReadSByte().ToString(),
        ConstantTypeCode.Boolean => r.ReadBoolean().ToString(),
        ConstantTypeCode.Char => "'" + r.ReadChar() + "'",
        ConstantTypeCode.Single => r.ReadSingle().ToString(),
        ConstantTypeCode.Double => r.ReadDouble().ToString(),
        ConstantTypeCode.String => "\"" + r.ReadUTF16(r.Length) + "\"",
        _ => "?",
    };
}

// Renders signature types as C#-ish names.
sealed class SigProvider(MetadataReader md) : ISignatureTypeProvider<string, object?>
{
    public string TypeName(EntityHandle h) => h.Kind switch
    {
        HandleKind.TypeDefinition => Def(md.GetTypeDefinition((TypeDefinitionHandle)h)),
        HandleKind.TypeReference => Ref(md.GetTypeReference((TypeReferenceHandle)h)),
        HandleKind.TypeSpecification => md.GetTypeSpecification((TypeSpecificationHandle)h).DecodeSignature(this, null),
        _ => "?",
    };
    string Def(TypeDefinition t)
    {
        var name = md.GetString(t.Name);
        var decl = t.GetDeclaringType();
        if (!decl.IsNil) return Def(md.GetTypeDefinition(decl)) + "." + Strip(name);
        var ns = md.GetString(t.Namespace);
        return ns.Length == 0 ? Strip(name) : ns + "." + Strip(name);
    }
    string Ref(TypeReference r)
    {
        var name = md.GetString(r.Name);
        if (r.ResolutionScope.Kind == HandleKind.TypeReference)
            return Ref(md.GetTypeReference((TypeReferenceHandle)r.ResolutionScope)) + "." + Strip(name);
        var ns = md.GetString(r.Namespace);
        var full = ns.Length == 0 ? Strip(name) : ns + "." + Strip(name);
        return full switch
        {
            "System.Collections.Generic.IEnumerable" => "IEnumerable",
            "System.Collections.Generic.IReadOnlyList" => "IReadOnlyList",
            "System.Collections.Generic.IReadOnlyCollection" => "IReadOnlyCollection",
            "System.Collections.Generic.List" => "List",
            "System.Collections.Generic.Dictionary" => "Dictionary",
            "System.Collections.Generic.IReadOnlyDictionary" => "IReadOnlyDictionary",
            "System.Collections.Immutable.ImmutableArray" => "ImmutableArray",
            "System.Action" => "Action", "System.Func" => "Func", "System.EventHandler" => "EventHandler",
            "System.Nullable" => "Nullable",
            _ => full,
        };
    }
    static string Strip(string n) { var i = n.IndexOf('`'); return i < 0 ? n : n[..i]; }

    public string GetPrimitiveType(PrimitiveTypeCode code) => code switch
    {
        PrimitiveTypeCode.Boolean => "bool", PrimitiveTypeCode.Byte => "byte", PrimitiveTypeCode.SByte => "sbyte",
        PrimitiveTypeCode.Char => "char", PrimitiveTypeCode.Int16 => "short", PrimitiveTypeCode.UInt16 => "ushort",
        PrimitiveTypeCode.Int32 => "int", PrimitiveTypeCode.UInt32 => "uint", PrimitiveTypeCode.Int64 => "long",
        PrimitiveTypeCode.UInt64 => "ulong", PrimitiveTypeCode.Single => "float", PrimitiveTypeCode.Double => "double",
        PrimitiveTypeCode.IntPtr => "nint", PrimitiveTypeCode.UIntPtr => "nuint", PrimitiveTypeCode.Object => "object",
        PrimitiveTypeCode.String => "string", PrimitiveTypeCode.Void => "void", PrimitiveTypeCode.TypedReference => "TypedReference",
        _ => code.ToString(),
    };
    public string GetTypeFromDefinition(MetadataReader r, TypeDefinitionHandle h, byte rawTypeKind) => Def(r.GetTypeDefinition(h));
    public string GetTypeFromReference(MetadataReader r, TypeReferenceHandle h, byte rawTypeKind) => Ref(r.GetTypeReference(h));
    public string GetTypeFromSpecification(MetadataReader r, object? g, TypeSpecificationHandle h, byte rawTypeKind) => r.GetTypeSpecification(h).DecodeSignature(this, g);
    public string GetSZArrayType(string e) => e + "[]";
    public string GetArrayType(string e, ArrayShape s) => e + "[" + new string(',', s.Rank - 1) + "]";
    public string GetByReferenceType(string e) => "ref " + e;
    public string GetPointerType(string e) => e + "*";
    public string GetPinnedType(string e) => e;
    public string GetGenericInstantiation(string g, ImmutableArray<string> a) => g + "<" + string.Join(", ", a) + ">";
    public string GetGenericTypeParameter(object? g, int i) => "T" + i;
    public string GetGenericMethodParameter(object? g, int i) => "M" + i;
    public string GetFunctionPointerType(MethodSignature<string> s) => "delegate*<" + string.Join(", ", s.ParameterTypes.Append(s.ReturnType)) + ">";
    public string GetModifiedType(string m, string u, bool req) => u;
}
