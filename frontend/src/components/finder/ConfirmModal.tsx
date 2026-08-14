import type { CSSProperties, ReactNode } from 'react';
import { WB_FONT, FS } from './theme';

/**
 * 全站统一确认弹窗：界面正中模态框（不再用悬浮 Popconfirm）。
 * 字体随父容器继承终端 WB_FONT，标题 13 加粗、正文 13，与终端字号一致。
 * 满足「删除/确认弹窗居中」规范——全站所有「删除 / 确认」类弹窗统一使用本组件。
 *
 * 由原 pages/terminal/ConfirmModal.tsx 搬移至此，作为全站唯一实现；
 * 终端与管理端视图均从本模块导入。
 */

const OVERLAY: CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.3)', zIndex: 1000,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
};

const CARD: CSSProperties = {
  width: 380, maxWidth: 'calc(100vw - 32px)', background: '#fff', borderRadius: 12,
  boxShadow: '0 12px 32px rgba(0,0,0,0.18)', overflow: 'hidden',
};

const BTN: CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: FS.aux, color: '#1d1d1f',
  background: '#eef0f3', border: 'none', cursor: 'pointer', padding: '5px 14px', borderRadius: 6,
  height: 28,
};

export interface ConfirmModalProps {
  open: boolean;
  title: ReactNode;
  desc?: ReactNode;
  /** 确认按钮文案，默认「删除」。 */
  okText?: string;
  /** 确认按钮风格，danger=红色。 */
  okDanger?: boolean;
  loading?: boolean;
  onCancel: () => void;
  onOk: () => void;
}

export default function ConfirmModal(props: ConfirmModalProps) {
  const { open, title, desc, okText = '删除', okDanger = true, loading, onCancel, onOk } = props;
  if (!open) return null;
  return (
    <div style={{ ...OVERLAY, fontFamily: WB_FONT }} onClick={onCancel}>
      <div style={CARD} onClick={(e) => e.stopPropagation()}>
        <div style={{ padding: '14px 18px', fontSize: FS.body, fontWeight: 600, color: '#1d1d1f', borderBottom: '1px solid #E5E7EB' }}>
          {title}
        </div>
        <div style={{ padding: '18px', fontSize: FS.body, color: '#1d1d1f', lineHeight: 1.5 }}>
          {desc ?? '此操作不可撤销，确定继续？'}
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '0 18px 16px' }}>
          <button style={BTN} onClick={onCancel}>取消</button>
          <button
            style={{ ...BTN, background: okDanger ? '#ff3b30' : '#6366F1', color: '#fff', border: 'none' }}
            disabled={loading}
            onClick={onOk}
          >
            {loading ? `${okText}中…` : okText}
          </button>
        </div>
      </div>
    </div>
  );
}
