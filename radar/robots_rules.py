"""Robots availability is distinct from a protected target document (RFC9309)."""
import urllib.error,urllib.robotparser

def read_robots(origin,domain,fetch):
    robot=urllib.robotparser.RobotFileParser();status='rules_read'
    try:robot.parse(fetch(origin+'/robots.txt',domain).splitlines())
    except urllib.error.HTTPError as error:
        # These are responses for robots.txt alone, not permission to bypass a
        # document's 401/403, a login, explicit Disallow, 429 or server failure.
        if error.code not in (403,404,410):raise ValueError('无法确认来源网站的抓取规则')
        robot.parse([]);status='robots_unavailable_http_'+str(error.code)
    return robot,status
