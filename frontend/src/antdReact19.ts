import { unstableSetRender } from 'antd';
import { createRoot, type Root } from 'react-dom/client';

// Ant Design 5 static message/notification/modal APIs otherwise use the removed
// ReactDOM.render. Register the documented React 19 adapter before any UI call.
// https://5x-ant-design.antgroup.com/docs/react/v5-for-19
unstableSetRender((node, container) => {
  const target = container as typeof container & { __antdRoot?: Root };
  const root = target.__antdRoot ??= createRoot(container);
  root.render(node);
  return async () => {
    // Avoid unmounting a React root synchronously during another render.
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
    root.unmount();
    if (target.__antdRoot === root) delete target.__antdRoot;
  };
});
