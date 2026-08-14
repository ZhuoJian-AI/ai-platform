import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { Button, Select, Upload, message, Empty, Spin, Tag } from 'antd';
import type { UploadProps } from 'antd';
import { PhoneOutlined, UploadOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { organizations as orgApi, type Organization } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { FinderShell, TitleBar } from '../components/finder/primitives';
import ConfirmModal from '../components/finder/ConfirmModal';
import { WB, FS } from '../components/finder/theme';

/**
 * 组织联系方式配置页（/org/contact）：组织管理员上传「联系我们」二维码图片，
 * 该图将出现在本组织管理端登录页（/{slug}/login）与终端登录页（/{slug}/terminal/login）的
 * 「联系我们」弹出框中。未配置时点击「联系我们」不弹框。
 *
 * - 组织级账号：只能配置自己组织。
 * - 平台级账号：可挑选任意组织配置（Select 切换）。
 */
export default function ContactInfo() {
  const { admin, isSuperAdmin, isOrgScoped } = useAuth();

  // 平台级账号：选一个组织来配置；组织级账号：锁死自己组织
  const [selectedOrgId, setSelectedOrgId] = useState<string | null>(admin?.organization_id ?? null);

  const { data: orgList } = useQuery<Organization[]>({
    queryKey: ['orgs'],
    queryFn: orgApi.list,
  });

  // 组织级账号无 orgList 时不阻塞——直接用自己 org 的 slug
  const effectiveOrg = useMemo<Organization | null>(() => {
    if (isOrgScoped()) {
      // 组织级账号 /organizations 只返回自己组织，取首条
      return orgList?.[0] ?? null;
    }
    return orgList?.find((o) => o.id === selectedOrgId) ?? null;
  }, [orgList, selectedOrgId, isOrgScoped]);

  const slug = effectiveOrg?.slug ?? null;
  const orgId = effectiveOrg?.id ?? null;

  // 当前已配置的二维码图片：按 slug 免登录读取，刷新键 invalidate 后重新拉
  const previewKey = `contact-image:${slug ?? ''}`;
  const previewUrl = slug ? `/api/v1/public/orgs/${encodeURIComponent(slug)}/contact-image?t=${previewKey}` : null;
  const [previewOk, setPreviewOk] = useState<boolean | null>(null);
  useEffect(() => {
    setPreviewOk(null);
    if (!slug) return;
    let cancelled = false;
    orgApi.fetchContactImage(slug).then((url) => {
      if (cancelled) return;
      setPreviewOk(!!url);
      if (url) {
        // 与下方的 <img src={previewUrl}> 不同步——这里仅做存在性探测，object URL 立即释放
        URL.revokeObjectURL(url);
      }
    });
    return () => { cancelled = true; };
  }, [slug, previewKey]);

  const [delConfirm, setDelConfirm] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const uploadProps: UploadProps = {
    accept: 'image/*',
    showUploadList: false,
    maxCount: 1,
    disabled: !orgId || uploading,
    beforeUpload: (file) => {
      // 2MB 上限（与后端一致）
      if (file.size > 2 * 1024 * 1024) {
        message.error('图片过大（>2MB），请压缩后再上传');
        return Upload.LIST_IGNORE;
      }
      return true;
    },
    customRequest: async (opts) => {
      const { file, onSuccess, onError } = opts;
      if (!orgId) {
        onError?.(new Error('未选择组织'));
        return;
      }
      setUploading(true);
      try {
        await orgApi.uploadContactImage(orgId, file as File);
        onSuccess?.({}, undefined as never);
        message.success('联系方式图片已更新');
        // 强制 <img> 重新加载：改变 previewKey
        bumpPreviewKey();
        setPreviewOk(true);
      } catch (e) {
        const msg = (e as { message?: string })?.message || '上传失败';
        message.error(msg);
        onError?.(e as Error);
      } finally {
        setUploading(false);
      }
    },
  };

  // 用计数器作为 <img src> 的查询串，绕过浏览器缓存
  const [previewBump, setPreviewBump] = useState(0);
  const bumpPreviewKey = () => setPreviewBump((n) => n + 1);
  const imgSrc = slug
    ? `/api/v1/public/orgs/${encodeURIComponent(slug)}/contact-image?bump=${previewBump}`
    : null;

  const onDelete = async () => {
    if (!orgId) return;
    setDeleting(true);
    try {
      await orgApi.deleteContactImage(orgId);
      message.success('已删除联系方式图片');
      bumpPreviewKey();
      setPreviewOk(false);
    } catch (e) {
      message.error((e as { message?: string })?.message || '删除失败');
    } finally {
      setDeleting(false);
      setDelConfirm(false);
    }
  };

  return (
    <FinderShell>
      <TitleBar
        icon={<PhoneOutlined />}
        title="联系方式"
        titleExtra={
          isSuperAdmin() ? (
            <Select
              style={{ width: 260 }}
              placeholder="选择组织"
              value={selectedOrgId ?? undefined}
              onChange={(v) => setSelectedOrgId(v as string)}
              options={(orgList ?? []).map((o) => ({ value: o.id, label: `${o.name}（${o.slug}）` }))}
              showSearch
              optionFilterProp="label"
            />
          ) : null
        }
      />

      <div style={bodyStyle}>
        {!effectiveOrg ? (
          <div style={{ padding: 40, textAlign: 'center' }}>
            {orgList === undefined ? <Spin /> : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={isSuperAdmin() ? '请选择组织' : '当前账号未绑定组织'} />
            )}
          </div>
        ) : (
          <div style={cardStyle}>
            <div style={{ marginBottom: 12, color: WB.textAux, fontSize: FS.aux, lineHeight: 1.6 }}>
              {`上传的二维码图片将出现在本组织登录页（/${slug}/login、/${slug}/terminal/login）的「联系我们」弹出框中。未配置时，用户点击「联系我们」会收到提示并不弹框。`}
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
              <div style={previewBoxStyle}>
                {previewUrl && previewOk !== false ? (
                  <img
                    key={previewBump}
                    src={imgSrc ?? undefined}
                    alt="联系方式二维码"
                    style={{ maxWidth: '100%', maxHeight: 240, objectFit: 'contain', display: 'block', margin: '0 auto' }}
                    onLoad={() => setPreviewOk(true)}
                    onError={() => setPreviewOk(false)}
                  />
                ) : previewOk === false ? (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未配置联系方式图片" />
                ) : (
                  <Spin />
                )}
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 10, flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Tag color="blue">{effectiveOrg.name}</Tag>
                  <Tag>{effectiveOrg.slug}</Tag>
                </div>
                <div style={{ display: 'flex', gap: 10 }}>
                  <Upload {...uploadProps}>
                    <Button type="primary" icon={<UploadOutlined />} loading={uploading} disabled={!orgId}>
                      {previewOk ? '更换图片' : '上传图片'}
                    </Button>
                  </Upload>
                  <Button
                    icon={<DeleteOutlined />}
                    danger
                    disabled={!previewOk}
                    loading={deleting}
                    onClick={() => setDelConfirm(true)}
                  >
                    删除
                  </Button>
                  <Button icon={<ReloadOutlined />} onClick={() => { bumpPreviewKey(); }}>刷新预览</Button>
                </div>
                <div style={{ color: WB.textAux, fontSize: FS.micro, lineHeight: 1.6 }}>
                  支持 png / jpg / webp 等图片格式，单张不超过 2MB。建议方形二维码，清晰可扫。
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      <ConfirmModal
        open={delConfirm}
        title="删除联系方式图片？"
        desc="删除后，登录页「联系我们」将不再弹框。"
        onCancel={() => setDelConfirm(false)}
        onOk={() => { onDelete(); }}
      />
    </FinderShell>
  );
}

const bodyStyle: CSSProperties = {
  flex: 1, overflow: 'auto', padding: '20px 24px', display: 'flex', flexDirection: 'column',
};

const cardStyle: CSSProperties = {
  background: '#fff', border: `1px solid ${WB.border}`, borderRadius: 10,
  padding: 20, maxWidth: 760,
};

const previewBoxStyle: CSSProperties = {
  width: 260, height: 260, border: `1px solid ${WB.border}`, borderRadius: 8,
  background: '#fafafa', display: 'flex', alignItems: 'center', justifyContent: 'center',
  flexShrink: 0, overflow: 'hidden',
};
