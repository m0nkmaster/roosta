// The same local denials used by Claude/Cursor, applied before Pi executes tools.
import fs from 'node:fs';
import path from 'node:path';

const glob = (pattern, value) => new RegExp('^' + pattern.split('*').map(p => p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('.*') + '$', 'i').test(value);
function resolved(file, seen = new Set()) {
  let candidate = path.resolve(file), tail = [];
  while (!fs.existsSync(candidate)) {
    try {
      if (fs.lstatSync(candidate).isSymbolicLink()) {
        if (seen.has(candidate)) throw new Error('Symlink cycle');
        seen.add(candidate);
        return resolved(path.resolve(path.dirname(candidate), fs.readlinkSync(candidate), ...tail), seen);
      }
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
    tail.unshift(path.basename(candidate));
    const parent = path.dirname(candidate);
    if (parent === candidate) break;
    candidate = parent;
  }
  return path.join(fs.realpathSync(candidate), ...tail);
}
// Recognise one literal command only. Shell expansion and command composition stay denied.
function packageRead(command, policy, cwd) {
  const word = /[ \t]*(?:'([^'\r\n]*)'|"([^"$`\\!\r\n]*)"|([a-zA-Z0-9_./:+@%-]+))(?=[ \t]|$)/gy;
  const args = [];
  let offset = 0;
  command = command.replace(/[ \t]+$/, '');
  while (offset < command.length) {
    const match = word.exec(command);
    if (!match) return false;
    args.push(match[1] ?? match[2] ?? match[3]);
    offset = word.lastIndex;
  }
  const [program, file, operation, ...options] = args;
  const root = policy.readOnlyRoot;
  if (program === 'python3' && file === path.join(root, 'skills/workspace-learner/sessions.py')) {
    if (fs.realpathSync(file) !== file) return false;
    if (operation === 'status') return options.length === 0;
    if (operation === 'list') return options.every(arg => /^[\w-]+$/.test(arg));
    return operation === 'transcript' && /^(?:assistant:.+|(?:oc|cc|cursor):[\w.@-]+)$/.test(options[0])
      && (options.length === 1 || (options.length === 2 && options[1] === '--tools'));
  }
  const cat = program === 'cat' && args.length === 2;
  const search = program === 'grep' && args.length === 5 && file === '-F' && operation === '--';
  if (!cat && !search) return false;
  const target = args.at(-1);
  return target.startsWith(root + path.sep) && !target.split(path.sep).includes('..')
    && fs.existsSync(target) && fs.realpathSync(target).startsWith(root + path.sep)
    && fs.statSync(target).isFile() && !denied({toolName: 'read', input: {path: target}}, policy, cwd);
}
export function denied(event, policy, cwd = process.cwd()) {
  const tool = event.toolName, input = event.input || {};
  if (!policy || !Array.isArray(policy.deny)) return 'Roosta permission policy is missing';
  const fileTool = ['read', 'edit', 'write'].includes(tool);
  const file = fileTool ? resolved(path.resolve(cwd, input.path || '.')) : null;
  const command = tool === 'bash' ? String(input.command || '') : '';
  const targetsRoot = root => file === root || file?.startsWith(root + path.sep) || command.includes(root);
  if ((policy.protected || []).some(targetsRoot)) return 'AI credentials and runtime state are private';
  if (policy.readOnlyRoot && tool !== 'read' && targetsRoot(policy.readOnlyRoot)
      && !(tool === 'bash' && packageRead(command, policy, cwd))) {
    return 'The installed Roosta package is read-only';
  }

  if (policy.unrestricted) return '';
  if (tool.startsWith('mcp__')) {
    const name = tool.split('__').slice(2).join('__');
    for (const rule of policy.deny) {
      const keyword = /^Mcp\(\*:\*(.+)\*\)$/.exec(rule)?.[1];
      if (keyword && name.toLowerCase().includes(keyword.toLowerCase())) return 'External changes require approval';
    }
    return '';
  }
  if (tool === 'tool_search' || ['list_mcp_resources', 'list_mcp_resource_templates', 'read_mcp_resource'].includes(tool)) return '';
  if (!fileTool && tool !== 'bash') return 'Tool is outside the Roosta policy';
  if (fileTool) {
    const kind = tool === 'read' ? 'Read' : 'Write';
    for (const rule of policy.deny) {
      const match = /^(Read|Write)\((.*)\)$/.exec(rule);
      if (match?.[1] === kind && [input.path, path.relative(cwd, file), file, path.basename(file)].some(p => glob(match[2], p || ''))) return 'File is protected by the Roosta policy';
    }
  }
  if (tool === 'bash') {
    if (/(?:\.env\b|\.pem\b|\.key\b|auth\.json|credentials\.json)/i.test(command)) return 'Credential files are private';
    // Shell policies are guardrails, as in the other runtimes, not an OS sandbox.
    for (const rule of policy.deny) {
      const match = /^Shell\(([^:)]+)(?::(.*))?\)$/.exec(rule);
      if (!match) continue;
      const prefix = (match[1] + (match[2] ? ' ' + match[2].replace(/\*$/, '') : '')).trim();
      const words = prefix.split(/\s+/).map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+');
      if (new RegExp('(?:^|[\\s;/|&()])' + words + '(?:\\s|$|[;/|&()])', 'i').test(command.replace(/["']/g, ''))) return 'Command requires approval';
    }
  }
  return '';
}
export default function (pi) {
  const policy = JSON.parse(process.env.ROOSTA_PI_POLICY || 'null');
  if (!policy || !Array.isArray(policy.deny)) throw new Error('Missing Roosta policy');
  pi.on('session_start', (_event, ctx) => { ctx.ui.notify('roosta-policy-ready', 'info'); });
  pi.on('tool_call', event => {
    try {
      const reason = denied(event, policy);
      if (reason) return { block: true, reason };
    } catch {
      return { block: true, reason: 'Roosta could not validate this tool call' };
    }
  });
}
