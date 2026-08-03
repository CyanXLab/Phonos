export function StatsPage() {
  return (
    <div className="space-y-4">
      <div className="card">
        <h2 className="text-lg font-semibold mb-4">学习统计</h2>
        <p className="text-sm text-gray-500">
          统计页面正在开发中，将展示：
        </p>
        <ul className="text-sm space-y-1 mt-2 text-gray-600 dark:text-gray-300">
          <li>• 评分趋势图</li>
          <li>• 错误音素 Top N</li>
          <li>• 错误词 Top N</li>
          <li>• 错误题型 Top N</li>
          <li>• 最近 7 天趋势</li>
          <li>• 预测校准</li>
          <li>• 学习策略建议</li>
        </ul>
      </div>
    </div>
  );
}
