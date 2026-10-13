"""Data-only skill registry with confined schemas and repeatable geometry diagnostics."""
import hashlib
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry

EXECUTOR_PERMISSIONS = {
    'inspect': {'project:read'},
    'geometry': {'project:read', 'artifact:write'},
    'section': {'project:read', 'artifact:write'},
    'export': {'artifact:write'},
}
PERMISSIONS = {'project:read', 'artifact:write', 'reference:read'}
SCHEMA_DRAFT = 'https://json-schema.org/draft/2020-12/schema'
ISOLATION = '几何任务各自使用独立成果目录；CAD 写入由独立 STA 通道串行处理。此诊断不申请 CAD 锁、不写图、不调用模型。'
MAX_RESOURCE_BYTES = 1_048_576


def _blocked_retrieval(uri):
    raise ValueError('Schema 不允许读取外部引用。')


def _resource(folder, name):
    """Never open an absolute, escaping, or symlink-escaping manifest resource."""
    if not isinstance(name, str) or not name or Path(name).is_absolute() or ':' in name:
        raise ValueError('依赖和 Schema 必须是技能目录内的相对文件。')
    target = (folder / name).resolve()
    if not target.is_relative_to(folder.resolve()):
        raise ValueError('依赖或 Schema 路径越出技能目录。')
    if not target.is_file():
        raise ValueError(f'技能资源不存在：{name}')
    if target.stat().st_size > MAX_RESOURCE_BYTES:
        raise ValueError(f'技能资源超过 1 MiB：{name}')
    return target.read_bytes()


def _check_schema(schema):
    if not isinstance(schema, (dict, bool)):
        raise ValueError('input_schema 必须包含 JSON Schema 对象或布尔值。')
    pending = [schema]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ('$ref', '$dynamicRef', '$recursiveRef') and (not isinstance(value, str) or not value.startswith('#')):
                    raise ValueError('Schema 只允许文档内部的 # 引用；禁止外部 $ref。')
                if key == '$id' and (not isinstance(value, str) or not value.startswith('#')):
                    raise ValueError('Schema 不允许改变引用基址的外部 $id。')
                if key == '$schema' and value not in (SCHEMA_DRAFT, SCHEMA_DRAFT + '#'):
                    raise ValueError('当前技能 Schema 仅支持 JSON Schema Draft 2020-12。')
                if isinstance(value, (dict, list)):
                    pending.append(value)
        elif isinstance(node, list):
            pending.extend(value for value in node if isinstance(value, (dict, list)))
    Draft202012Validator.check_schema(schema)


def _permission_errors(skill):
    errors = []
    executor = skill.get('executor')
    if executor not in EXECUTOR_PERMISSIONS:
        errors.append('执行器未注册；不允许运行技能目录中的自定义脚本。')
    permissions = skill.get('permissions')
    if not isinstance(permissions, list) or any(not isinstance(p, str) for p in permissions):
        errors.append('permissions 必须为已登记权限的字符串数组。')
    else:
        if set(permissions) - PERMISSIONS:
            errors.append('permissions 包含白名单外的权限。')
        if executor in EXECUTOR_PERMISSIONS and EXECUTOR_PERMISSIONS[executor] - set(permissions):
            errors.append('缺少执行器所需权限：' + '、'.join(sorted(EXECUTOR_PERMISSIONS[executor] - set(permissions))))
    return errors

BUILTIN=[
 {'id':'inspect-project','name':'底图与项目检查','description':'检查单位、坐标、图层与中心线输入','executor':'inspect','permissions':['project:read']},
 {'id':'road-plan','name':'控规道路平面','description':'确定性道路几何、真实圆弧与 CAD 落图','executor':'geometry','permissions':['project:read','artifact:write']},
 {'id':'urban-renewal','name':'城市更新微调整','description':'保留对象约束、方案 A/B 与冲突定位','executor':'geometry','permissions':['project:read','artifact:write']},
 {'id':'export-dxf','name':'质量校核与 DXF 导出','description':'校核真实实体、单位、曲线并导出','executor':'export','permissions':['artifact:write']},
 {'id':'road-cross-section','name':'道路横断面','description':'明确组成宽度、横坡和基准高程后生成可编辑教学剖面','executor':'section','permissions':['project:read','artifact:write']},
 {'id':'beijing-regulatory-cad','name':'北京控规 CAD 工作流','description':'本机参考库检索、来源检查、道路生成与成果整理；非完整控规自动审批','executor':'geometry','permissions':['project:read','artifact:write','reference:read']},
]
def _describe(skill, folder, states, diagnostics, *, local, manifest_bytes=b'', initial_errors=()):
    x = {**skill, 'source': 'local' if local else 'builtin'}
    x.setdefault('version', '0.1.0')
    x.setdefault('name', x['id'])
    errors = list(initial_errors) + _permission_errors(x)
    digest = hashlib.sha256(b'planning-skill-registry-v1\0')
    digest.update(manifest_bytes or json.dumps(skill, sort_keys=True, ensure_ascii=False).encode('utf-8'))
    x['schema_definition'] = None
    x['schema_enforcement'] = 'json_schema_draft_2020_12_and_registered_executor'
    x['isolation'] = ISOLATION
    try:
        if not folder.resolve().is_relative_to(folder.parent.resolve()):
            raise ValueError('技能目录不能链接到 skills 目录以外。')
        if (folder / 'SKILL.md').exists() or local:
            content = _resource(folder, 'SKILL.md')
            digest.update(b'\0SKILL.md\0' + content)
            x['instructions'] = content.decode('utf-8-sig')
        else:
            x['instructions'] = x.get('description', '')
        schema_name = x.get('input_schema')
        if not local and x['id'] == 'road-cross-section' and (folder / 'schema.json').exists():
            schema_name = 'schema.json'
            x['input_schema'] = schema_name
        if schema_name is not None:
            content = _resource(folder, schema_name)
            digest.update(b'\0schema\0' + content)
            schema = json.loads(content)
            _check_schema(schema)
            x['schema_definition'] = schema
        dependencies = x.get('dependencies', [])
        if not isinstance(dependencies, list) or len(dependencies) > 50:
            raise ValueError('dependencies 必须为不超过 50 项的技能内相对文件路径数组。')
        for dependency in dependencies:
            content = _resource(folder, dependency)
            digest.update(b'\0dependency\0' + dependency.encode('utf-8') + b'\0' + content)
    except (OSError, ValueError, TypeError, RecursionError, SchemaError) as exc:
        errors.append(str(exc)[:500])
    x['content_hash'] = digest.hexdigest()
    x['validation_errors'] = errors
    x['ready'] = not errors
    diagnostic = diagnostics.get(x['id'])
    current = bool(diagnostic and diagnostic.get('content_hash') == x['content_hash'])
    x['diagnostic'] = diagnostic
    x['validation_state'] = ('invalid' if errors else 'stale' if diagnostic and not current
                             else diagnostic['status'] if current else 'not_diagnosed' if local else 'builtin_registered')
    state = states.get(x['id'], {})
    x['enabled'] = bool(x['ready'] and state.get('enabled', not local))
    if local:
        # A subsequent edit never silently re-enables a previously enabled draft.
        x['enabled'] = bool(x['enabled'] and current and diagnostic.get('status') == 'passed'
                            and state.get('content_hash') == x['content_hash'])
    return x


def list_skills(root, store):
    states = {s['id']: s for s in store.list('skill_states')}
    diagnostics = {s['id']: s for s in store.list('skill_diagnostics')}
    folder = Path(root) / 'skills'
    items = [_describe(skill, folder / skill['id'], states, diagnostics, local=False) for skill in BUILTIN]
    builtin_ids = {s['id'] for s in BUILTIN}
    for doc in sorted(folder.glob('*/manifest.json')):
        if doc.parent.name in builtin_ids:
            continue
        raw, errors = b'', []
        x = {'id': doc.parent.name, 'name': doc.parent.name}
        try:
            if not doc.parent.resolve().is_relative_to(folder.resolve()):
                raise ValueError('技能目录不能链接到 skills 目录以外。')
            raw = _resource(doc.parent, 'manifest.json')
            manifest = json.loads(raw)
            if not isinstance(manifest, dict):
                raise ValueError('manifest 必须为对象。')
            if manifest.get('id') != doc.parent.name or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', manifest.get('id', '')):
                raise ValueError('manifest id 必须与技能目录名一致，且只含小写字母、数字、连字符。')
            # Public fields cannot inject a fake diagnostic, source or executable code.
            x.update({k: manifest[k] for k in ('id', 'name', 'description', 'version', 'executor', 'permissions', 'input_schema', 'dependencies') if k in manifest})
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            errors.append(str(exc)[:500])
        items.append(_describe(x, doc.parent, states, diagnostics, local=True, manifest_bytes=raw, initial_errors=errors))
    return items


def _find(root, store, skill_id):
    for skill in list_skills(root, store):
        if skill['id'] == skill_id:
            return skill
    raise KeyError(skill_id)


def _validate_contract(skill, spec):
    errors = list(skill.get('validation_errors', [])) + _permission_errors(skill)
    if errors:
        raise ValueError('技能校验失败：' + '；'.join(dict.fromkeys(errors)))
    if not isinstance(spec, dict):
        raise ValueError('技能输入必须为 RoadSpec 对象。')
    if skill['executor'] not in ('geometry', 'section'):
        raise ValueError('此执行器不是道路几何任务，不能用于几何试运行。')
    if (skill['executor'] == 'section') != (spec.get('kind') == 'road_cross_section'):
        raise ValueError('技能执行器与道路平面/横断面输入类型不一致。')
    schema = skill.get('schema_definition')
    if schema is not None:
        try:
            _check_schema(schema)
            validator = Draft202012Validator(schema, registry=Registry(retrieve=_blocked_retrieval))
            messages = []
            for error in validator.iter_errors(spec):
                path = '.'.join(str(p) for p in error.absolute_path) or '$'
                messages.append(f'{path}: {error.message[:240]}')
                if len(messages) >= 10:
                    break
            if messages:
                raise ValueError('输入未通过技能 Schema：' + '；'.join(messages))
        except Exception as exc:
            raise ValueError('Schema 校验失败：' + str(exc)[:1500]) from exc


def validate_skill_input(skill, spec):
    """Validate the current registry snapshot before submitting or changing a job."""
    if not skill.get('ready') or not skill.get('enabled'):
        raise ValueError('技能尚未就绪或未启用。')
    if skill.get('source') == 'local':
        diagnostic = skill.get('diagnostic') or {}
        if skill.get('validation_state') != 'passed' or diagnostic.get('status') != 'passed' or diagnostic.get('content_hash') != skill.get('content_hash'):
            raise ValueError('本地技能需先完成当前版本的真实几何诊断，再显式启用。')
    _validate_contract(skill, spec)


def diagnose_skill(root, store, skill_id):
    """Run only a fixed synthetic geometry example; never import skill code or call CAD/API."""
    skill = _find(root, store, skill_id)
    result = {'id': skill_id, 'content_hash': skill['content_hash'], 'status': 'failed', 'success': False,
              'errors': [], 'warnings': [], 'checks': [], 'entity_count': 0, 'metrics': {},
              'scope': '内置合成案例的真实几何试运行；不调用模型、不写 CAD、不创建成果文件。',
              'isolation': ISOLATION, 'synthetic': True}
    try:
        if skill.get('executor') == 'section':
            from .sections import generate, get_example
            spec = get_example()
            result['example'] = 'road-cross-section'
        else:
            from .geometry import generate
            from .cases import get_case
            spec = get_case('regulatory-road-plan')['spec']
            result['example'] = 'regulatory-road-plan'
        _validate_contract(skill, spec)
        result['checks'].append('登记、目录内依赖、权限和输入 Schema 校验通过。')
        generated = generate(spec)
        result['errors'] = generated.get('report', {}).get('errors', [])
        result['warnings'] = generated.get('report', {}).get('warnings', [])
        result['entity_count'] = len(generated.get('entities', []))
        result['metrics'] = generated.get('metrics', {})
        if not result['entity_count']:
            result['errors'].append({'code': 'empty_preview', 'message': '试运行未生成任何几何实体。'})
        if not result['errors']:
            result.update(status='passed', success=True)
            result['checks'].append('已实际调用注册几何引擎，生成实体且报告无阻断错误。')
    except Exception as exc:
        result['errors'].append({'code': 'skill_diagnostic_failed', 'message': str(exc)[:1500]})
    # Files changed during execution cannot authorize the newer content.
    if _find(root, store, skill_id)['content_hash'] != result['content_hash']:
        result.update(status='failed', success=False)
        result['errors'].append({'code': 'skill_changed', 'message': '诊断期间技能文件已改变，请重新诊断。'})
    return store.put('skill_diagnostics', result)


def toggle_skill(root, store, skill_id, enabled):
    if not isinstance(enabled, bool):
        raise ValueError('enabled 必须为布尔值。')
    skill = _find(root, store, skill_id)
    if enabled:
        if not skill['ready']:
            raise ValueError('技能登记无效：' + '；'.join(skill['validation_errors']))
        if skill['source'] == 'local' and skill['validation_state'] != 'passed':
            raise ValueError('本地技能当前内容尚未通过真实几何诊断；请先试运行，再启用。')
    store.put('skill_states', {'id': skill_id, 'enabled': enabled, 'content_hash': skill['content_hash']})
    return _find(root, store, skill_id)
