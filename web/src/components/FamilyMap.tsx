import { useMemo, useState } from 'react'
import { Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useNavigate } from 'react-router'
import type { MemeNode, TreeResponse } from '@contract/types'
import { useIsNarrow } from '../hooks/useIsNarrow'
import { useShowSensitive } from '../hooks/useShowSensitive'
import { layoutFamily, NODE_H, NODE_W, type PostGroup } from '../lib/familyLayout'
import { abbreviateLatin } from '../lib/latin'
import { NodeThumb } from './SpecimenCard'

type MemeData = { node: MemeNode; selected: boolean; onPath: boolean }
type MoreData = { hidden: number }
type PostsData = { group: PostGroup }
type MemeFlowNode = Node<MemeData, 'meme'>
type MoreFlowNode = Node<MoreData, 'more'>
type PostsFlowNode = Node<PostsData, 'posts'>

const hiddenHandle = { opacity: 0, pointerEvents: 'none' } as const

function MemeBox({ data }: NodeProps<MemeFlowNode>) {
  const { node, selected, onPath } = data
  const longestWord = Math.max(...node.name.split(/\s+/).map((w) => w.length))
  const nameSize = longestWord > 8 ? 'text-sm' : node.name.length > 16 ? 'text-base' : 'text-xl'
  const border = selected ? 'border-4 border-stamp' : onPath ? 'border-[3px] border-stamp' : 'border-2 border-ink'
  return (
    <div
      className={`flex cursor-pointer items-center gap-2 bg-paper p-1.5 ${border}`}
      style={{ width: NODE_W, height: NODE_H }}
    >
      <Handle type="target" position={Position.Top} style={hiddenHandle} />
      <NodeThumb node={node} className="h-[68px] w-[68px]" />
      <div className="min-w-0" title={node.name}>
        <div
          className={`line-clamp-2 font-extrabold leading-tight ${nameSize}`}
        >
          {node.name}
        </div>
        {node.latin_name && (
          <div className="truncate text-base italic" title={node.latin_name}>
            {abbreviateLatin(node.latin_name)}
          </div>
        )}
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

/** A group of the selected meme's posts: the newest picture, what they use, how many. */
function PostsBox({ data }: NodeProps<PostsFlowNode>) {
  const { group } = data
  return (
    <div
      className="flex cursor-pointer items-center gap-2 border-2 border-dotted border-ink bg-paper p-1.5"
      style={{ width: NODE_W, height: NODE_H }}
      title={group.nodeId ? `Open ${group.label}` : `Show these posts`}
    >
      <Handle type="target" position={Position.Top} style={hiddenHandle} />
      <img src={group.thumb} alt="" loading="lazy" className="h-[68px] w-[68px] shrink-0 border border-ink object-cover" />
      <div className="min-w-0">
        <div className="line-clamp-2 text-base font-bold leading-tight">{group.label}</div>
        <div className="font-type text-sm">
          {group.count} {group.count === 1 ? 'post' : 'posts'}
          {group.nodeId ? ' →' : ''}
        </div>
      </div>
    </div>
  )
}

const nodeTypes = { meme: MemeBox, more: MoreBox, posts: PostsBox }

interface Props {
  tree: TreeResponse
  /** A group of the selected meme's own posts was clicked: show just those in the side panel. */
  onPostsClick?: (group: PostGroup) => void
}

/**
 * The whole character-line family as a top-to-bottom map, with the selected meme's posts
 * hanging under it in groups. Click a meme to open it, a group to see its posts.
 */
export function FamilyMap({ tree, onPostsClick }: Props) {
  const navigate = useNavigate()
  const narrow = useIsNarrow()
  const showSensitive = useShowSensitive()
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set())

  const { nodes, edges, legend } = useMemo(() => {
    const layout = layoutFamily(tree, expanded, showSensitive)
    const flowNodes: (MemeFlowNode | MoreFlowNode | PostsFlowNode)[] = layout.nodes.map((n) =>
      n.kind === 'meme'
        ? { id: n.id, type: 'meme', position: { x: n.x, y: n.y }, data: { node: n.node, selected: n.selected, onPath: n.onPath } }
        : n.kind === 'more'
          ? { id: n.id, type: 'more', position: { x: n.x, y: n.y }, data: { hidden: n.hidden } }
          : { id: n.id, type: 'posts', position: { x: n.x, y: n.y }, data: { group: n.group } },
    )
    const flowEdges: Edge[] = layout.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: 'smoothstep',
      style: {
        stroke: e.onPath ? 'var(--color-stamp)' : 'var(--color-ink-soft)',
        strokeWidth: e.onPath ? 4 : 2,
        strokeDasharray: e.posts ? '2 5' : e.inferred ? '8 6' : undefined,
      },
    }))
    const links = layout.edges.filter((e) => !e.posts)
    const legend = {
      cited: links.some((e) => !e.inferred),
      inferred: links.some((e) => e.inferred),
      posts: layout.edges.some((e) => e.posts),
    }
    return { nodes: flowNodes, edges: flowEdges, legend }
  }, [tree, expanded, showSensitive])

  // Fitting a wide family into a phone screen shrinks every card past reading: open on the
  // selected meme at a readable zoom instead, and let the reader pan to the relatives.
  const focusSelected = narrow && nodes.some((n) => n.id === tree.selected_id)
  const fitViewOptions = focusSelected
    ? { nodes: [{ id: tree.selected_id }], minZoom: 0.75, maxZoom: 0.75 }
    : { padding: 0.05, maxZoom: tree.family_ids.length <= 1 ? 0.9 : 1.1 }

  return (
    <>
    <ReactFlow
      key={`${expanded.size}:${focusSelected}`} // refit after "+N" expands or the screen changes shape
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={fitViewOptions}
      minZoom={0.15}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      onNodeClick={(_, node) => {
        if (node.type === 'more') {
          const parentId = node.id.slice('more:'.length)
          setExpanded((prev) => new Set(prev).add(parentId))
        } else if (node.type === 'posts') {
          const { group } = (node as PostsFlowNode).data
          if (group.nodeId) navigate(`/meme/${group.nodeId}`)
          else onPostsClick?.(group)
        } else {
          navigate(`/meme/${node.id}`)
        }
      }}
      proOptions={{ hideAttribution: true }}
    />
    {(legend.cited || legend.inferred || legend.posts) && (
      <div className="font-type pointer-events-none absolute right-3 top-3 z-10 border border-ink bg-paper px-2 py-1 text-sm">
        {legend.cited && (
          <div className="flex items-center gap-2">
            <span className="inline-block w-8 border-t-2 border-ink-soft" /> cited
          </div>
        )}
        {legend.inferred && (
          <div className="flex items-center gap-2">
            <span className="inline-block w-8 border-t-2 border-dashed border-ink-soft" /> citation needed
          </div>
        )}
        {legend.posts && (
          <div className="flex items-center gap-2">
            <span className="inline-block w-8 border-t-2 border-dotted border-ink-soft" /> posts seen
          </div>
        )}
      </div>
    )}
    </>
  )
}
