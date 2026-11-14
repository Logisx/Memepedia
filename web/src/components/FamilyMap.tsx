import { useMemo, useState } from 'react'
import { Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useNavigate } from 'react-router'
import type { MemeNode, TreeResponse } from '@contract/types'
import { layoutFamily, NODE_H, NODE_W } from '../lib/familyLayout'
import { NodeThumb } from './SpecimenCard'

type MemeData = { node: MemeNode; selected: boolean; onPath: boolean }
type MoreData = { hidden: number }
type MemeFlowNode = Node<MemeData, 'meme'>
type MoreFlowNode = Node<MoreData, 'more'>

const hiddenHandle = { opacity: 0, pointerEvents: 'none' } as const

function MemeBox({ data }: NodeProps<MemeFlowNode>) {
  const { node, selected, onPath } = data
  const border = selected ? 'border-4 border-stamp' : onPath ? 'border-[3px] border-stamp' : 'border-2 border-ink'
  return (
    <div
      className={`flex cursor-pointer items-center gap-2 bg-paper p-1.5 ${border}`}
      style={{ width: NODE_W, height: NODE_H }}
    >
      <Handle type="target" position={Position.Top} style={hiddenHandle} />
      <NodeThumb node={node} className="h-[60px] w-[60px]" />
      <div className="min-w-0">
        <div className="line-clamp-2 text-lg font-extrabold leading-tight">{node.name}</div>
        {node.latin_name && <div className="truncate text-sm italic">{node.latin_name}</div>}
      </div>
      <Handle type="source" position={Position.Bottom} style={hiddenHandle} />
    </div>
  )
}

function MoreBox({ data }: NodeProps<MoreFlowNode>) {
  return (
    <div
      className="font-type flex cursor-pointer flex-col items-center justify-center border-2 border-dashed border-ink bg-paper text-xl"
      style={{ width: NODE_W, height: NODE_H }}
    >
      <Handle type="target" position={Position.Top} style={hiddenHandle} />
      <span className="text-2xl font-bold">+{data.hidden}</span>
      <span className="text-sm">click to show</span>
    </div>
  )
}

const nodeTypes = { meme: MemeBox, more: MoreBox }

/** The whole character-line family as a top-to-bottom map. Click a meme to open it. */
export function FamilyMap({ tree }: { tree: TreeResponse }) {
  const navigate = useNavigate()
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set())

  const { nodes, edges } = useMemo(() => {
    const layout = layoutFamily(tree, expanded)
    const flowNodes: (MemeFlowNode | MoreFlowNode)[] = layout.nodes.map((n) =>
      n.kind === 'meme'
        ? { id: n.id, type: 'meme', position: { x: n.x, y: n.y }, data: { node: n.node, selected: n.selected, onPath: n.onPath } }
        : { id: n.id, type: 'more', position: { x: n.x, y: n.y }, data: { hidden: n.hidden } },
    )
    const flowEdges: Edge[] = layout.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: 'smoothstep',
      style: {
        stroke: e.onPath ? 'var(--color-stamp)' : 'var(--color-ink-soft)',
        strokeWidth: e.onPath ? 4 : 2,
        strokeDasharray: e.inferred ? '8 6' : undefined,
      },
    }))
    return { nodes: flowNodes, edges: flowEdges }
  }, [tree, expanded])

  return (
    <ReactFlow
      key={expanded.size} // refit the view after "+N" expands
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.1, maxZoom: 1.1 }}
      minZoom={0.15}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      onNodeClick={(_, node) => {
        if (node.type === 'more') {
          const parentId = node.id.slice('more:'.length)
          setExpanded((prev) => new Set(prev).add(parentId))
        } else {
          navigate(`/meme/${node.id}`)
        }
      }}
      proOptions={{ hideAttribution: true }}
    />
  )
}
