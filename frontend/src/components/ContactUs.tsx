import { useEffect, useState } from 'react';
import { Modal, message } from 'antd';
import { CustomerServiceOutlined } from '@ant-design/icons';
import { WB, FS } from './finder/theme';
import { organizations } from '../api/client';

/**
 * 「联系我们」链接 + 二维码悬浮框。
 * 放在登录按钮右侧：点击弹出 Modal 展示客服/咨询二维码。
 *
 * 二维码图片由组织管理员在「组织管理 → 联系方式」上传，按组织 slug 免登录读取。
 * - 若传入 ``slug`` 为空（如超管登录页），不渲染该入口。
 * - 若该组织未上传图片，点击时提示「管理员未配置」并拒绝弹框。
 */
export default function ContactUs({ slug, style }: { slug?: string; style?: React.CSSProperties }) {
  const [open, setOpen] = useState(false);
  const [imgUrl, setImgUrl] = useState<string | null>(null);

  useEffect(() => {
    return () => {
      if (imgUrl) URL.revokeObjectURL(imgUrl);
    };
  }, [imgUrl]);

  if (!slug) return null;

  const onClick = async (e: React.MouseEvent) => {
    e.preventDefault();
    const url = await organizations.fetchContactImage(slug);
    if (!url) {
      message.info('管理员尚未配置联系方式图片');
      return;
    }
    // 释放上一次的 object URL，避免内存泄漏
    if (imgUrl) URL.revokeObjectURL(imgUrl);
    setImgUrl(url);
    setOpen(true);
  };

  return (
    <>
      <a
        onClick={onClick}
        style={{
          fontSize: FS.aux,
          color: WB.textAux,
          whiteSpace: 'nowrap',
          cursor: 'pointer',
          ...style,
        }}
      >
        <CustomerServiceOutlined style={{ marginRight: 4 }} />
        联系我们
      </a>

      <Modal
        title={<span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><CustomerServiceOutlined />联系我们</span>}
        open={open}
        onCancel={() => setOpen(false)}
        footer={null}
        centered
        width={360}
        destroyOnClose
      >
        <div style={{ textAlign: 'center', padding: '8px 0 4px' }}>
          {imgUrl && (
            <img
              src={imgUrl}
              alt="联系我们二维码"
              style={{ width: 220, height: 220, objectFit: 'contain', display: 'block', margin: '0 auto' }}
            />
          )}
          <div style={{ marginTop: 12, color: WB.text, fontSize: FS.body, fontWeight: 500 }}>
            扫码联系我们
          </div>
        </div>
      </Modal>
    </>
  );
}
