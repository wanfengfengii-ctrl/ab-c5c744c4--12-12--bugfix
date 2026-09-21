import { useCallback, useEffect, useMemo, useState } from 'react'
import { fetchHealth, reconstruct } from './api.js'

// ----- projection vector helpers -----------------------------------------

function resizeVec(vec, n) {
  const next = Array.from({ length: n }, (_, i) => vec[i] ?? '0')
  return next
}

function toNumberOrRaw(s) {
  const t = String(s).trim()
  if (t === '') return null
  return /^[+-]?\d+$/.test(t) ? Number(t) : t
}

// Parse a locator key directly; the backend already uses "row[2]" form.

// Initial projections of the canonical 4x4 switching component:
//   .01. / 1... / ...1 / .1..  ==  .10. / ...1 / 1... / ..1.
// Both grids share these four projection families.
const INITIAL_PROJ = {
  row: ['1', '1', '1', '1'],
  col: ['1', '1', '1', '1'],
  diff: ['0', '1', '1', '0', '1', '1', '0'],
  sum: ['0', '1', '1', '0', '1', '1', '0'],
}

const FAMILIES = [
  { key: 'row', title: '行投影（自上而下 r）', label: (i) => `r=${i}` },
  { key: 'col', title: '列投影（自左向右 c）', label: (i) => `c=${i}` },
  {
    key: 'diff',
    title: '对角投影 r−c（按差值递增）',
    label: (i, { cols }) => `r−c=${i - (cols - 1)}`,
  },
  {
    key: 'sum',
    title: '对角投影 r+c（按和值递增）',
    label: (i) => `r+c=${i}`,
  },
]

export default function App() {
  const [rows, setRows] = useState(4)
  const [cols, setCols] = useState(4)

  const [proj, setProj] = useState(() => ({
    row: INITIAL_PROJ.row.slice(),
    col: INITIAL_PROJ.col.slice(),
    diff: INITIAL_PROJ.diff.slice(),
    sum: INITIAL_PROJ.sum.slice(),
  }))
  const [known, setKnown] = useState([])
  const [result, setResult] = useState(null) // successful API body (may be none)
  const [errors, setErrors] = useState([])
  const [topMessage, setTopMessage] = useState('')
  const [loading, setLoading] = useState(false)
  const [activeWitness, setActiveWitness] = useState(0)
  const [health, setHealth] = useState('checking')

  useEffect(() => {
    let alive = true
    const ping = () =>
      fetchHealth()
        .then(() => alive && setHealth('ok'))
        .catch(() => alive && setHealth('down'))
    ping()
    const t = setInterval(ping, 8000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  // Reset stale grids whenever the input specification is edited.
  const invalidate = useCallback(() => {
    setResult(null)
    setErrors([])
    setTopMessage('')
    setActiveWitness(0)
  }, [])

  const changeDim = (which, raw) => {
    const n = Number(raw)
    if (!Number.isInteger(n)) return
    if (which === 'rows') {
      setRows(n)
      setProj((p) => ({
        ...p,
        row: resizeVec(p.row, n),
        diff: resizeVec(p.diff, n + cols - 1),
        sum: resizeVec(p.sum, n + cols - 1),
      }))
    } else {
      setCols(n)
      setProj((p) => ({
        ...p,
        col: resizeVec(p.col, n),
        diff: resizeVec(p.diff, rows + n - 1),
        sum: resizeVec(p.sum, rows + n - 1),
      }))
    }
    setKnown((ks) => ks.filter((k) => {
      const r = Number(k.row)
      const c = Number(k.col)
      return Number.isInteger(r) && Number.isInteger(c) &&
        (which === 'rows' ? r < n : true) &&
        (which === 'cols' ? c < n : true)
    }))
    invalidate()
  }

  const setVecCell = (fam, i, value) => {
    setProj((p) => {
      const vec = p[fam].slice()
      vec[i] = value
      return { ...p, [fam]: vec }
    })
    invalidate()
  }

  const setKnownCell = (i, patch) => {
    setKnown((ks) => ks.map((k, j) => (j === i ? { ...k, ...patch } : k)))
    invalidate()
  }

  const addKnown = () =>
    setKnown((ks) => [...ks, { row: '0', col: '0', value: '1' }])

  const removeKnown = (i) => setKnown((ks) => ks.filter((_, j) => j !== i))

  // ----- error lookup ----------------------------------------------------
  const errorByField = useMemo(() => {
    const m = new Map()
    for (const e of errors) {
      if (!m.has(e.field)) m.set(e.field, e)
      // Also mark the parent container, e.g. known[1] for known[1].row.
      const parent = e.field.split('.')[0]
      if (parent !== e.field && !m.has(parent)) m.set(parent, e)
    }
    return m
  }, [errors])

  const errFor = (field) => errorByField.get(field)

  // ----- submission ------------------------------------------------------
  const submit = async () => {
    setLoading(true)
    setErrors([])
    setTopMessage('')
    const payload = {
      rows,
      cols,
      row: proj.row.map(toNumberOrRaw),
      col: proj.col.map(toNumberOrRaw),
      diff: proj.diff.map(toNumberOrRaw),
      sum: proj.sum.map(toNumberOrRaw),
      known: known.map((k) => ({
        row: toNumberOrRaw(k.row),
        col: toNumberOrRaw(k.col),
        value: toNumberOrRaw(k.value),
      })),
    }
    let out
    try {
      out = await reconstruct(payload)
    } catch (e) {
      setLoading(false)
      setResult(null)
      setTopMessage(`无法连接重建服务：${e.message}`)
      return
    }
    setLoading(false)

    if (out.kind === 'error') {
      // Illegal input: clear any old grid and show locatable feedback.
      setResult(null)
      setActiveWitness(0)
      setErrors(out.body?.errors ?? [])
      setTopMessage(out.body?.message ?? `请求被拒绝（HTTP ${out.status}）`)
      return
    }

    const body = out.body
    if (body.status === 'none') {
      // Certified no-solution: the old grid must not linger.
      setResult(body)
      setActiveWitness(0)
      return
    }
    setResult(body)
    setActiveWitness(0)
  }

  const loadAmbiguousExample = () => {
    setRows(4)
    setCols(4)
    setProj({
      row: INITIAL_PROJ.row.slice(),
      col: INITIAL_PROJ.col.slice(),
      diff: INITIAL_PROJ.diff.slice(),
      sum: INITIAL_PROJ.sum.slice(),
    })
    setKnown([])
    invalidate()
  }

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>复合材料截面 · 四向投影复核台</h1>
          <p className="subtitle">
            行 / 列 / r−c / r+c 四向二值投影重建 · 穷举判定无解 · 唯一 · 多解
          </p>
        </div>
        <div className={`health health-${health}`}>
          API {health === 'ok' ? '● 在线' : health === 'down' ? '● 不可达' : '○ 探测中'}
        </div>
      </header>

      <main className="layout">
        <section className="panel editor">
          <div className="dims">
            <label>
              行数（4–12）
              <input
                type="number" min={4} max={12}
                className={errFor('rows') ? 'invalid' : ''}
                value={rows}
                onChange={(e) => changeDim('rows', e.target.value)}
              />
            </label>
            <label>
              列数（4–12）
              <input
                type="number" min={4} max={12}
                className={errFor('cols') ? 'invalid' : ''}
                value={cols}
                onChange={(e) => changeDim('cols', e.target.value)}
              />
            </label>
            <button type="button" className="ghost" onClick={loadAmbiguousExample}>
              载入歧义示例
            </button>
          </div>

          {FAMILIES.map((fam) => (
            <ProjectionEditor
              key={fam.key}
              fam={fam}
              ctx={{ cols }}
              values={proj[fam.key]}
              errFor={errFor}
              onChange={(i, v) => setVecCell(fam.key, i, v)}
            />
          ))}

          <KnownEditor
            rows={rows}
            cols={cols}
            known={known}
            errFor={errFor}
            onChange={setKnownCell}
            onAdd={addKnown}
            onRemove={removeKnown}
          />

          <div className="actions">
            <button className="primary" disabled={loading} onClick={submit}>
              {loading ? '重建中…' : '发起重建（真实 API）'}
            </button>
            {topMessage && <div className="topmsg error">{topMessage}</div>}
          </div>

          {errors.length > 0 && (
            <div className="errorlist" role="alert">
              <strong>可定位的输入问题（{errors.length}）：</strong>
              <ul>
                {errors.map((e, i) => (
                  <li key={i}>
                    <code className="field">{e.field}</code> — {e.message}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>

        <section className="panel result">
          <ResultPane
            result={result}
            activeWitness={activeWitness}
            setActiveWitness={setActiveWitness}
            known={known}
          />
        </section>
      </main>

      <footer className="foot">
        行列从零编号；位串按行优先排列，0 先于 1；多解仅返回最小的两个见证。
      </footer>
    </div>
  )
}

// ----- projection vector editor ------------------------------------------

function ProjectionEditor({ fam, ctx, values, errFor, onChange }) {
  return (
    <div className="fam">
      <h3>{fam.title}</h3>
      <div className="vec">
        {values.map((v, i) => {
          const field = `${fam.key}[${i}]`
          const e = errFor(field)
          return (
            <label key={i} className={`veccell ${e ? 'has-error' : ''}`} title={e?.message}>
              <span className="veclabel">{fam.label(i, ctx)}</span>
              <input
                type="number"
                className={e ? 'invalid' : ''}
                value={v}
                min={0}
                onChange={(ev) => onChange(i, ev.target.value)}
              />
            </label>
          )
        })}
      </div>
    </div>
  )
}

// ----- known cells editor ------------------------------------------------

function KnownEditor({ rows, cols, known, errFor, onChange, onAdd, onRemove }) {
  return (
    <div className="fam">
      <h3>已知单元（不得重复或冲突）</h3>
      {known.length === 0 && <p className="muted">暂无已知单元，可直接添加。</p>}
      {known.map((k, i) => {
        const wholeErr = errFor(`known[${i}]`)
        return (
          <div key={i} className={`knownrow ${wholeErr ? 'has-error' : ''}`}>
            <label>
              行
              <input
                type="number" min={0} max={rows - 1}
                className={errFor(`known[${i}].row`) ? 'invalid' : ''}
                value={k.row}
                onChange={(e) => onChange(i, { row: e.target.value })}
              />
            </label>
            <label>
              列
              <input
                type="number" min={0} max={cols - 1}
                className={errFor(`known[${i}].col`) ? 'invalid' : ''}
                value={k.col}
                onChange={(e) => onChange(i, { col: e.target.value })}
              />
            </label>
            <label>
              值
              <select
                className={errFor(`known[${i}].value`) ? 'invalid' : ''}
                value={k.value}
                onChange={(e) => onChange(i, { value: e.target.value })}
              >
                <option value="1">1（夹杂）</option>
                <option value="0">0（基体）</option>
              </select>
            </label>
            <button type="button" className="ghost danger" onClick={() => onRemove(i)}>
              删除
            </button>
            {wholeErr && <span className="rowerr">{wholeErr.message}</span>}
          </div>
        )
      })}
      <button type="button" className="ghost" onClick={onAdd}>+ 添加已知单元</button>
    </div>
  )
}

// ----- result pane: status banner, grid toggle, per-line witnesses -------

function ResultPane({ result, activeWitness, setActiveWitness, known }) {
  if (!result) {
    return (
      <div className="placeholder">
        <p>编辑左侧四向投影与已知单元，点击「发起重建」。</p>
        <p className="muted">
          非法输入或判定无解时，此处旧网格会被清除并给出可定位反馈。
        </p>
      </div>
    )
  }

  if (result.status === 'none') {
    return (
      <div className="status-banner none">
        <h2>判定：无解</h2>
        <p>
          在当前四向投影与已知单元约束下，穷举搜索证明<strong>不存在任何二值截面</strong>。
          旧网格已清除，请核对左侧被标记的投影线。
        </p>
      </div>
    )
  }

  const diffSet = new Set(result.differences.map((d) => d.index))
  const witness = result.witnesses[activeWitness]

  return (
    <div>
      <div className={`status-banner ${result.status}`}>
        {result.status === 'unique' ? (
          <h2>判定：唯一解</h2>
        ) : (
          <h2>判定：多解 — 存在斜向投影无法察觉的伪截面</h2>
        )}
        <p className="bitstring">位串：<code>{witness.grid}</code></p>
      </div>

      {result.status === 'multiple' && (
        <div className="witness-switch">
          {result.witnesses.map((_, i) => (
            <button
              key={i}
              className={i === activeWitness ? 'seg active' : 'seg'}
              onClick={() => setActiveWitness(i)}
            >
              见证 {i + 1}（第 {i + 1} 小位串）
            </button>
          ))}
          <span className="muted">
            {result.differences.length} 个差异单元已高亮，可切换核对。
          </span>
        </div>
      )}

      <Grid
        grid={witness.grid}
        rows={result.rows}
        cols={result.cols}
        diffSet={diffSet}
        allWitnesses={result.witnesses}
        activeWitness={activeWitness}
        known={known}
      />

      <LineWitness result={result} witness={witness} cols={result.cols} />
    </div>
  )
}

function Grid({ grid, rows, cols, diffSet, allWitnesses, activeWitness, known }) {
  const knownMap = useMemo(() => {
    const m = new Map()
    for (const k of known) {
      const r = Number(k.row)
      const c = Number(k.col)
      if (Number.isInteger(r) && Number.isInteger(c)) m.set(r * cols + c, Number(k.value))
    }
    return m
  }, [known, cols])

  return (
    <div className="gridwrap">
      <div
        className="grid"
        style={{ gridTemplateColumns: `repeat(${cols}, max-content)` }}
      >
        {grid.split('').map((ch, i) => {
          const r = Math.floor(i / cols)
          const c = i % cols
          const isDiff = diffSet.has(i)
          const other =
            allWitnesses && allWitnesses.length === 2
              ? allWitnesses[1 - activeWitness].grid[i]
              : null
          const knownHere = knownMap.has(i)
          const cls = [
            'cell',
            ch === '1' ? 'one' : 'zero',
            isDiff ? 'diff' : '',
            knownHere ? 'known' : '',
          ].filter(Boolean).join(' ')
          return (
            <div
              key={i}
              className={cls}
              title={
                `(${r},${c}) = ${ch}` +
                (isDiff ? `；另一见证为 ${other}` : '') +
                (knownHere ? '；已知单元' : '')
              }
            >
              {ch}
              {knownHere && <span className="knownmark">知</span>}
              {isDiff && <span className="diffmark">{ch}↔{other}</span>}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ----- per-line actual vs target verification table ----------------------

function LineWitness({ result, witness, cols }) {
  const targets = result.targets
  const actuals = witness.lines
  return (
    <div className="lines">
      <h3>逐线核对：见证实算和 vs 目标值</h3>
      {FAMILIES.map((fam) => {
        const tgt = targets[fam.key]
        const act = actuals[fam.key]
        let mismatch = 0
        return (
          <div key={fam.key} className="linefam">
            <h4>{fam.title}</h4>
            <div className="linegrid">
              {tgt.map((t, i) => {
                const a = act[i]
                const ok = a === t
                if (!ok) mismatch++
                return (
                  <div key={i} className={`linecell ${ok ? 'match' : 'mismatch'}`}>
                    <span className="linetag">{fam.label(i, { cols })}</span>
                    <span className="linevals">
                      <strong>{a}</strong>
                      <span className="arrow">/</span>
                      <span>{t}</span>
                    </span>
                    <span className="linemark">{ok ? '✓' : '✗'}</span>
                  </div>
                )
              })}
            </div>
            {mismatch > 0 && <p className="rowerr">{mismatch} 条线不匹配！</p>}
          </div>
        )
      })}
    </div>
  )
}
